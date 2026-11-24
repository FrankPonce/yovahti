#!/usr/bin/env bash
# Real LTE stack for the RAN spike (I35): srsRAN 4G (EPC + eNB + UE) over a ZeroMQ virtual
# radio inside WSL. Run as root. The UE lives in network namespace ue1 (IP from the EPC,
# 172.16.0.x); the EPC's SGi side is 172.16.0.1.
#
#   ran.sh setup        configs into /opt/ran (once)
#   ran.sh up           EPC + eNB + UE, wait until the UE has an IP
#   ran.sh enb-stop     "sleep" the cell: stop the eNB (the UE loses the radio link)
#   ran.sh enb-start    "wake" the cell: start the eNB
#   ran.sh state        prints: enb=<0|1> ue_ip=<ip|none> ping_ms=<rtt|none>
#   ran.sh iperf [s]    downlink TCP throughput to the UE for s seconds (Mbit/s)
#   ran.sh down         stop everything
set -u
SRS=/opt/srsRAN_4G/build
CONF=/opt/ran
LOG=/tmp/ran
mkdir -p "$LOG"

ZMQ_ENB="fail_on_disconnect=true,tx_port=tcp://*:2000,rx_port=tcp://localhost:2001,id=enb,base_srate=23.04e6"
ZMQ_UE="tx_port=tcp://*:2001,rx_port=tcp://localhost:2000,id=ue,base_srate=23.04e6"

setup() {
  mkdir -p "$CONF"
  for f in srsenb/enb.conf srsenb/sib.conf srsenb/rr.conf srsenb/rb.conf srsue/ue.conf \
           srsepc/epc.conf srsepc/user_db.csv; do
    cp "/opt/srsRAN_4G/$f.example" "$CONF/$(basename "$f")"
  done
  ip netns list | grep -q ue1 || ip netns add ue1
}

enb_start() {
  (cd "$CONF" && setsid nohup "$SRS/srsenb/src/srsenb" enb.conf --rf.device_name=zmq \
     --rf.device_args="$ZMQ_ENB" --enb_files.sib_config=sib.conf \
     --enb_files.rr_config=rr.conf --enb_files.rb_config=rb.conf \
     --log.filename="$LOG/enb.log" > "$LOG/enb.out" 2>&1 &)
}

enb_stop() { pkill -INT -x srsenb; for _ in $(seq 50); do pgrep -x srsenb >/dev/null || return 0; sleep 0.1; done; pkill -KILL -x srsenb; }

ue_ip() { ip netns exec ue1 ip -4 -o addr show tun_srsue 2>/dev/null | awk '{print $4}' | cut -d/ -f1; }

ue_start() {
  (cd "$CONF" && setsid nohup "$SRS/srsue/src/srsue" ue.conf --rf.device_name=zmq \
     --rf.device_args="$ZMQ_UE" --gw.netns=ue1 --log.filename="$LOG/ue.log" \
     > "$LOG/ue.out" 2>&1 &)
}

ue_stop() { pkill -INT -x srsue; for _ in $(seq 50); do pgrep -x srsue >/dev/null || return 0; sleep 0.1; done; pkill -KILL -x srsue; }

# The ZeroMQ virtual radio cannot reconnect once a peer restarts, so a sleeping cell also
# stops its UE, and a wake restarts both: the UE does a full power-on attach (an upper bound
# on a real UE's re-attach, which would find the cell again by itself).
cell_sleep() { ue_stop; enb_stop; }
cell_wake() { enb_start; sleep 1; ue_start; }
# wake as the loop uses it: returns once traffic flows (or retries ran out)
wake() { t0=$(date +%s.%N); te=none; cell_wake; wait_traffic; echo "traffic_s=$tr ue_retries=$retries"; }

up() {
  setup
  (cd "$CONF" && setsid nohup "$SRS/srsepc/src/srsepc" epc.conf --hss.db_file=user_db.csv \
     --log.filename="$LOG/epc.log" > "$LOG/epc.out" 2>&1 &)
  sleep 2
  enb_start
  sleep 3
  ue_start
  t0=$(date +%s.%N); te=none; wait_traffic
  [ "$tr" != none ] && { echo "ue_ip=$(ue_ip) ue_retries=$retries"; return 0; }
  echo "ue did not attach"; return 1
}

# Wait until user-plane packets reach the UE, timed from $t0. The ZeroMQ UE sometimes hangs
# at "Attaching UE..." and its ZMQ link wedges the eNB too; after 30 s both are restarted,
# at most 3 times (counted in $retries; the timing then includes the failed tries).
wait_traffic() {
  local ip now last
  tr=none; retries=0; last=$(date +%s)
  while :; do
    now=$(date +%s.%N)
    [ "$te" = none ] && grep -q "eNodeB started" "$LOG/enb.out" 2>/dev/null && te=$(echo "$now - $t0" | bc)
    ip=$(ue_ip)
    if [ -n "$ip" ] && ping -c1 -W0.2 "$ip" >/dev/null 2>&1; then tr=$(echo "$now - $t0" | bc); return; fi
    if [ $(( $(date +%s) - last )) -ge 30 ]; then
      [ "$retries" -ge 3 ] && return
      retries=$((retries + 1)); cell_sleep; cell_wake; last=$(date +%s)
    fi
    sleep 0.05
  done
}

state() {
  local e=0 ip rtt
  pgrep -x srsenb >/dev/null && e=1
  ip=$(ue_ip); rtt=none
  if [ -n "$ip" ]; then
    rtt=$(ping -c1 -W3 "$ip" 2>/dev/null | sed -n 's/.*time=\([0-9.]*\).*/\1/p'); rtt=${rtt:-none}
  fi
  echo "enb=$e ue_ip=${ip:-none} ping_ms=$rtt"
}

iperf() {
  local s=${1:-5}
  pgrep -x iperf3 >/dev/null || setsid ip netns exec ue1 iperf3 -s -D
  sleep 0.5
  iperf3 -c "$(ue_ip)" -t "$s" -J 2>/dev/null | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(round(d["end"]["sum_received"]["bits_per_second"]/1e6,2))' 2>/dev/null \
    || echo none
}

# one sleep/wake cycle, timed inside WSL (no wsl.exe overhead in the numbers):
# prints off_s=<asleep for> enb_ready_s=<start -> "eNodeB started"> traffic_s=<start -> UE ping ok>
trial() {
  local off=${1:-10}
  te=none
  cell_sleep; sleep "$off"
  : > "$LOG/enb.out"
  t0=$(date +%s.%N); cell_wake
  wait_traffic
  echo "off_s=$off enb_ready_s=$te traffic_s=$tr ue_retries=$retries"
}

down() { pkill -INT -x srsue; enb_stop; pkill -INT -x srsepc; pkill -x iperf3; sleep 1; }

case "${1:-}" in
  setup) setup ;; up) up ;; enb-stop) cell_sleep ;; enb-start) wake ;;
  state) state ;; iperf) iperf "${2:-5}" ;; trial) trial "${2:-10}" ;; down) down ;;
  *) echo "usage: ran.sh setup|up|enb-stop|enb-start|state|iperf [s]|down"; exit 2 ;;
esac
