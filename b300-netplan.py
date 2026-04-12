#!/usr/bin/env python3
# gen_nccl_netplan.py
#
# 케이블 연결 파일 형식 (--cable-file):
#   서버-케이블포트 > 서버-케이블포트
#   예)
#   1-1 > 2-1
#   1-2 > 2-2
#   1-3 > 3-3
#   빈 줄 / # 주석 무시
#
# 예시:
# python3 gen_nccl_netplan.py --servers 3 --cable-file cables.txt
# python3 gen_nccl_netplan.py --servers 3 --cable-file cables.txt --dual-port --mtu 9000

import argparse
import sys
from collections import defaultdict

# pciconf card idx → (np0 ifname, np1 ifname)
DEFAULT_CARD_IFACES = {
    0: ("eno10np0",    "enp23s0f1np1"),   # pciconf0
    1: ("eno12np0",    "enp57s0f1np1"),   # pciconf1
    2: ("eno13np0",    "enp95s0f1np1"),   # pciconf2
    3: ("eno11np0",    "enp112s0f1np1"),  # pciconf3
    4: ("eno7np0",     "enp151s0f1np1"),  # pciconf4
    5: ("eno9np0",     "enp185s0f1np1"),  # pciconf5
    6: ("eno8np0",     "enp220s0f1np1"),  # pciconf6
    7: ("eno6np0",     "enp237s0f1np1"),  # pciconf7
}

# 외부 케이블 번호(1~8, 왼쪽→오른쪽) → pciconf card idx
CABLE_TO_CARD = [7, 4, 6, 5, 0, 3, 1, 2]  # index 0 = 케이블1
NUM_CABLES = len(CABLE_TO_CARD)


# ── 케이블 파일 파싱 & 검증 ──────────────────────────────────────────

def parse_cable_file(path: str, num_servers: int):
    errors = []
    links = []
    used_ports = defaultdict(set)   # srv → set of cable port nos
    seen_pairs = set()

    try:
        f = open(path)
    except FileNotFoundError:
        raise SystemExit(f"[ERROR] 파일을 찾을 수 없습니다: '{path}'")

    with f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            # 형식 검사
            if ">" not in line:
                errors.append(f"  줄 {lineno}: '>' 구분자 없음 → '{line}'")
                continue

            left, _, right = line.partition(">")
            left, right = left.strip(), right.strip()

            def parse_side(s, side_name):
                parts = s.split("-")
                if len(parts) != 2:
                    errors.append(
                        f"  줄 {lineno}: {side_name} 형식 오류 (서버-포트 필요) → '{s}'"
                    )
                    return None
                try:
                    return int(parts[0]), int(parts[1])
                except ValueError:
                    errors.append(
                        f"  줄 {lineno}: {side_name} 숫자 변환 실패 → '{s}'"
                    )
                    return None

            a = parse_side(left,  "왼쪽")
            b = parse_side(right, "오른쪽")
            if a is None or b is None:
                continue

            srv_a, port_a = a
            srv_b, port_b = b
            ok = True

            # 서버 번호 범위
            for srv, label in [(srv_a, "왼쪽"), (srv_b, "오른쪽")]:
                if srv < 1 or srv > num_servers:
                    errors.append(
                        f"  줄 {lineno}: {label} 서버 번호 {srv} 범위 초과 (1~{num_servers})"
                    )
                    ok = False

            # 케이블 포트 번호 범위
            for port, label in [(port_a, "왼쪽"), (port_b, "오른쪽")]:
                if port < 1 or port > NUM_CABLES:
                    errors.append(
                        f"  줄 {lineno}: {label} 케이블 포트 번호 {port} 범위 초과 (1~{NUM_CABLES})"
                    )
                    ok = False

            # 같은 서버끼리
            if srv_a == srv_b:
                errors.append(
                    f"  줄 {lineno}: 같은 서버({srv_a})끼리 연결할 수 없음"
                )
                ok = False

            if not ok:
                continue

            # 포트 중복 사용
            for srv, port, label in [(srv_a, port_a, "왼쪽"), (srv_b, port_b, "오른쪽")]:
                if port in used_ports[srv]:
                    errors.append(
                        f"  줄 {lineno}: 서버{srv}의 케이블포트{port} 중복 사용 ({label})"
                    )
                    ok = False
                else:
                    used_ports[srv].add(port)

            # 양방향 중복
            key = frozenset([(srv_a, port_a), (srv_b, port_b)])
            if key in seen_pairs:
                errors.append(
                    f"  줄 {lineno}: 중복 연결 "
                    f"(srv{srv_a}-port{port_a} ↔ srv{srv_b}-port{port_b})"
                )
                ok = False
            else:
                seen_pairs.add(key)

            if not ok:
                continue

            # 정렬: 작은 srv 번호가 앞
            if srv_a > srv_b:
                srv_a, port_a, srv_b, port_b = srv_b, port_b, srv_a, port_a
            links.append(((srv_a, port_a), (srv_b, port_b)))

    if errors:
        print(f"[ERROR] 케이블 파일 '{path}'에서 {len(errors)}개 오류 발견:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        raise SystemExit(1)

    if not links:
        raise SystemExit(f"[ERROR] '{path}'에 유효한 연결이 없습니다.")

    return links


# ── IP 할당 ──────────────────────────────────────────────────────────

def pair_block(i: int, j: int) -> int:
    return 100 + i * 10 + j


def assign_ips(links, ip_prefix: int, dual_port: bool):
    pair_counter = defaultdict(int)
    entries = []

    for (srv_a, port_a), (srv_b, port_b) in links:
        pb = pair_block(srv_a, srv_b)
        pair_counter[(srv_a, srv_b)] += 1
        l = pair_counter[(srv_a, srv_b)]

        card_idx_a = CABLE_TO_CARD[port_a - 1]
        card_idx_b = CABLE_TO_CARD[port_b - 1]
        np0_a, np1_a = DEFAULT_CARD_IFACES[card_idx_a]
        np0_b, np1_b = DEFAULT_CARD_IFACES[card_idx_b]

        base = (l - 1) * 2
        ip_a_np0 = f"{ip_prefix}.{pb}.{base+1}.1/30"
        ip_b_np0 = f"{ip_prefix}.{pb}.{base+1}.2/30"
        ip_a_np1 = f"{ip_prefix}.{pb}.{base+2}.1/30"
        ip_b_np1 = f"{ip_prefix}.{pb}.{base+2}.2/30"

        entries.append(dict(
            srv_a=srv_a, port_a=port_a,
            srv_b=srv_b, port_b=port_b,
            card_idx_a=card_idx_a, card_idx_b=card_idx_b,
            np0_a=np0_a, np1_a=np1_a,
            np0_b=np0_b, np1_b=np1_b,
            ip_a_np0=ip_a_np0, ip_b_np0=ip_b_np0,
            ip_a_np1=ip_a_np1, ip_b_np1=ip_b_np1,
            link_no=l,
            label_np0=f"srv{srv_a}<->srv{srv_b} L{l} (cable{port_a}-cable{port_b}) np0",
            label_np1=f"srv{srv_a}<->srv{srv_b} L{l} (cable{port_a}-cable{port_b}) np1",
        ))

    return entries


# ── 출력 ─────────────────────────────────────────────────────────────

def emit(entries, num_servers, mtu, dual_port):
    up    = defaultdict(list)
    flush = defaultdict(list)
    addr  = defaultdict(list)
    ping  = defaultdict(list)
    seen  = defaultdict(set)

    def add(srv, iface, cidr, dst, label):
        if iface not in seen[srv]:
            seen[srv].add(iface)
            up[srv].append(iface)
            flush[srv].append(iface)
        addr[srv].append((iface, cidr))
        ping[srv].append((iface, dst.split("/")[0], label))

    for e in entries:
        add(e["srv_a"], e["np0_a"], e["ip_a_np0"], e["ip_b_np0"], e["label_np0"])
        add(e["srv_b"], e["np0_b"], e["ip_b_np0"], e["ip_a_np0"], e["label_np0"])
        if dual_port:
            add(e["srv_a"], e["np1_a"], e["ip_a_np1"], e["ip_b_np1"], e["label_np1"])
            add(e["srv_b"], e["np1_b"], e["ip_b_np1"], e["ip_a_np1"], e["label_np1"])

    print("# ===== LINK PLAN =====")
    for e in entries:
        print(
            f"# srv{e['srv_a']}(cable{e['port_a']}→card{e['card_idx_a']})"
            f" <-> "
            f"srv{e['srv_b']}(cable{e['port_b']}→card{e['card_idx_b']})"
            f"  L{e['link_no']}"
        )
        print(f"#   np0: {e['np0_a']} {e['ip_a_np0']}  <->  {e['np0_b']} {e['ip_b_np0']}")
        if dual_port:
            print(f"#   np1: {e['np1_a']} {e['ip_a_np1']}  <->  {e['np1_b']} {e['ip_b_np1']}")

    for s in range(1, num_servers + 1):
        if s not in up:
            print(f"\n## ===== server{s} ===== (연결 없음)")
            continue
        print(f"\n## ===== server{s} =====")
        print("# --- link up ---")
        for iface in up[s]:
            print(f"ip link set {iface} up mtu {mtu}")
        print("# --- flush ---")
        for iface in flush[s]:
            print(f"ip addr flush dev {iface}")
        print("# --- addr add ---")
        for iface, cidr in addr[s]:
            print(f"ip addr add {cidr} dev {iface}")

    for s in range(1, num_servers + 1):
        print(f"\n## ===== server{s} =====")
        print("\n# --- ping test (-c 3) ---")
        for iface, dst, label in ping[s]:
            print(f"ping -I {iface} -c 3 {dst}")


# ── main ─────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="NCCL 직결 네트워크 설정 명령 생성기 (ConnectX8 기준)"
    )
    p.add_argument("--servers", type=int, required=True, help="서버 대수 (2 이상)")
    p.add_argument("--cable-file", required=True,
                   help="케이블 연결 파일 (형식: '서버-포트 > 서버-포트')")
    p.add_argument("--dual-port", action="store_true",
                   help="카드당 np0+np1 두 포트 모두 사용 (기본: np0만)")
    p.add_argument("--ip-prefix", type=int, default=10,
                   help="IP 첫 번째 옥텟 (기본 10)")
    p.add_argument("--mtu", type=int, default=9000, help="MTU (기본 9000)")
    args = p.parse_args()

    if args.servers < 2:
        raise SystemExit("--servers 는 2 이상이어야 합니다.")

    print("# ===== INPUT =====")
    print(f"# servers={args.servers}, cable-file={args.cable_file}, "
          f"dual-port={args.dual_port}, "
          f"ip-prefix={args.ip_prefix}, mtu={args.mtu}")
    print("# 케이블 번호 → card idx → (np0, np1):")
    for i, card_idx in enumerate(CABLE_TO_CARD):
        np0, np1 = DEFAULT_CARD_IFACES[card_idx]
        print(f"#   케이블{i+1}: card{card_idx}  {np0} / {np1}")
    print()

    links   = parse_cable_file(args.cable_file, args.servers)
    entries = assign_ips(links, args.ip_prefix, args.dual_port)
    emit(entries, args.servers, args.mtu, args.dual_port)


if __name__ == "__main__":
    main()
