# b300_netplan.py

NCCL 직결(Back-to-Back) 네트워크 설정 명령 생성기입니다.  
케이블 연결 파일을 입력하면 각 서버별 `ip link` / `ip addr` / `ping` 명령을 출력합니다.

장비 기준: **NVIDIA ConnectX-8 400G** (mst 기준 pciconf0~7)

---

## 파일 구성

```
b300_netplan.py      # 메인 스크립트
cables.txt               # 4노드 12케이블 예시
```

---

## 케이블 연결 파일 형식 (`cables.txt`)

```
# 서버-케이블포트 > 서버-케이블포트
# 빈 줄과 # 주석은 무시됩니다

1-1 > 2-1
1-2 > 2-2
1-3 > 3-3
1-4 > 3-4
1-5 > 4-5
1-6 > 4-6
2-3 > 3-1
2-4 > 3-2
2-5 > 4-3
2-6 > 4-4
3-5 > 4-1
3-6 > 4-2
 
```

- **서버 번호**: 1부터 시작 (1, 2, 3, ...)
- **케이블 포트 번호**: 장비 외부에서 왼쪽부터 **1~8**

---

## 케이블 포트 → 내부 인터페이스 매핑

외부에서 보이는 케이블 포트 번호와 실제 인터페이스의 관계입니다.

| 케이블 포트 | pciconf card | np0 (기본) | np1 (--dual-port) |
|:-----------:|:------------:|:----------:|:-----------------:|
| 1 | card7 | eno6np0 | enp237s0f1np1 |
| 2 | card4 | eno7np0 | enp151s0f1np1 |
| 3 | card6 | eno8np0 | enp220s0f1np1 |
| 4 | card5 | eno9np0 | enp185s0f1np1 |
| 5 | card0 | eno10np0 * | enp23s0f1np1 |
| 6 | card3 | eno11np0 | enp112s0f1np1 |
| 7 | card1 | eno12np0 | enp57s0f1np1 |
| 8 | card2 | eno13np0 | enp95s0f1np1 |

---

## 사용법

### 4노드 12케이블

```bash
python3 gen_nccl_netplan.py --servers 4 --cable-file cables.txt --dual-port
```

### 옵션 전체

```bash
python3 gen_nccl_netplan.py \
    --servers 3 \           # 서버 대수 (필수)
    --cable-file cables.txt \  # 케이블 파일 경로 (필수)
    --dual-port \           # np0 + np1 모두 사용 (선택, 기본: np0만)
    --ip-prefix 10 \        # IP 첫 번째 옥텟 (기본: 10)
    --mtu 9000              # MTU (기본: 9000)
```

---

## 출력 예시 (3노드, np0 기준)

```
# ===== LINK PLAN =====
# srv1(cable1→card7) <-> srv2(cable1→card7)  L1
#   np0: eno6np0 10.112.1.1/30  <->  eno6np0 10.112.1.2/30
...

## ===== server1 =====
# --- link up ---
ip link set eno6np0 up mtu 9000
ip link set eno7np0 up mtu 9000
# --- flush ---
ip addr flush dev eno6np0
ip addr flush dev eno7np0
# --- addr add ---
ip addr add 10.112.1.1/30 dev eno6np0
ip addr add 10.112.5.1/30 dev eno7np0

# --- ping test (-c 3) ---
echo "# srv1<->srv2 L1 (cable1-cable1) np0"
ping -I eno6np0 -c 3 10.112.1.2
```

---

## IP 주소 규칙

```
{ip-prefix}.{서버쌍블록}.{서브넷}.{호스트}/30

서버쌍블록: 1↔2 = 112,  1↔3 = 113,  2↔3 = 123,  1↔4 = 114 ...
서브넷:      링크번호 L1 → 1 (np0), 2 (np1)
             링크번호 L2 → 5 (np0), 6 (np1)
```

예시:
- `srv1↔srv2 L1 np0` → `10.112.1.1/30` (srv1) / `10.112.1.2/30` (srv2)
- `srv1↔srv2 L1 np1` → `10.112.2.1/30` (srv1) / `10.112.2.2/30` (srv2)

---

## 케이블 파일 오류 검증

잘못된 파일을 입력하면 오류를 모아서 한 번에 출력합니다.

| 검사 항목 | 예시 |
|----------|------|
| `>` 구분자 없음 | `1 2-3` |
| 형식 오류 | `1 > 2-3` |
| 서버 번호 범위 초과 | `5-1 > 2-1` (서버 3대인데 5번) |
| 케이블 포트 번호 초과 | `1-9 > 2-1` (포트는 1~8) |
| 같은 서버끼리 연결 | `1-1 > 1-2` |
| 포트 중복 사용 | `1-1 > 2-1` 후 `1-1 > 3-2` |
| 양방향 중복 | `1-1 > 2-1` 후 `2-1 > 1-1` |

---

## 권장 구성 예시

| 노드 수 | 서버쌍 | 케이블 수 | 서버당 포트 사용 |
|:-------:|:------:|:---------:|:---------------:|
| 2노드 | 2쌍 | 2개 | 2포트 |
| 3노드 | 3쌍 | 6개 | 4포트 |
| 4노드 | 6쌍 | 12개 | 6포트 |

