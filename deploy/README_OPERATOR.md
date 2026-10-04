# 운영 배포 가이드

**이 문서는 릴리스 번들 안에 함께 담긴다.** 서버가 tar 하나만 받는 환경이어도
설치하는 자리에서 이것을 볼 수 있어야 한다.

---

## 0. 받아서 옮기고 푼다

번들은 **GitHub Actions 가 태그에서 만든다.** 저장소를 받는 PC 에서는 만들 수
없다 — Apptainer 는 리눅스 전용이다. 받는 것은 만들어진 `tar.gz` 하나다.

```bash
# 받는 PC 에서 — 저장소의 deploy/pc/fetch-release.{bat,sh} 가 최신 버전을 골라 받고 체크섬까지 본다.
# 손으로 받으면 (Windows PowerShell 의 curl 도 같은 줄로 된다):
curl -LO https://github.com/<소유자>/<저장소>/releases/download/<태그>/<slug>-<태그>.tar.gz
curl -LO https://github.com/<소유자>/<저장소>/releases/download/<태그>/<slug>-<태그>.tar.gz.sha256

scp <slug>-<태그>.tar.gz <계정>@<서버>:~/
```

서버에 붙어서:

```bash
ssh <계정>@<서버>

# **푸는 것보다 먼저 맞춰 본다.** 절반만 받아진 tar 는 푸는 순간에야 드러나고,
# 그때는 이미 배포하려고 서버에 붙어 있는 자리다.
sha256sum -c <slug>-<태그>.tar.gz.sha256    # sha256 파일도 함께 옮겼을 때

tar xzf <slug>-<태그>.tar.gz
cd <slug>-<태그>
ls
#  app.sif  deploy.sh  ha.sh  pg-ha.sh  backup.sh  restore.sh
#  app.service.template  worker.service.template
#  backup.service.template  backup.timer.template
#  .env.example  BUILD_INFO  README.md  쉬운-설치.md
#  apptainer_debs/  (폐쇄망용 apptainer .deb — prepare 가 먼저 본다)
```

> `/home` 에서 실행이 막히는 서버가 있다(noexec 마운트). 그때는 `/tmp` 에 풀어
> 실행한다 — 설치 **대상** 폴더는 그대로 `/home/<계정>/apps/<slug>` 다.

**번들 하나로 여러 플랫폼(인스턴스)을 설치한다.** 어느 플랫폼인지는 설치할 때 주는
`APP_SLUG` 가 정한다 — DB 이름 · systemd 유닛 · 설치 경로 · 주소 접두어가 전부 거기서 나온다.
`BUILD_INFO` 에는 버전과 **아무것도 안 줬을 때의 기본값**(틀의 이름 · 기본 포트)만 있다.

```bash
# 처음 한 번 — 이름 · 포트 · 확장을 준다. /etc/platform-instances/<slug>.conf 에 남는다
sudo APP_SLUG=plmhub APP_NAME="PLM 기준정보" APP_PORT=8040 EXTENSIONS=hub ./deploy.sh prepare
sudo APP_SLUG=plmhub ./deploy.sh install
# 그다음부터 — 이 서버에 인스턴스가 하나면 APP_SLUG 를 안 줘도 그것이다
sudo ./deploy.sh update
```

> **env 는 `sudo` 뒤에 붙인다** — `sudo APP_NAME=… ./deploy.sh update`. `APP_NAME=… sudo ./deploy.sh`
> 처럼 앞에 두면 우분투 기본 설정(`env_reset`)이 그 값을 **조용히 버린다**(24.04 운영 서버에서
> 확인, 2026-10-05). 스크립트에는 「안 줬다」 로 보여 기억한 값이나 기본값으로 그대로 진행한다.

| 설치 때 주는 것 | 뜻 | 나중에 |
| --- | --- | --- |
| `APP_SLUG` | 기계가 읽는 이름. 소문자·숫자 한 덩어리, 32자 이내 | **바꾸지 않는다** — DB · 쿠키 · 토큰 · 유닛이 다 걸린다 |
| `APP_NAME` · `APP_TAGLINE` | 화면에 보이는 이름 · 한 줄 설명 | `sudo APP_NAME=… ./deploy.sh update` 로 바꿀 수 있다 |
| `APP_PORT` | 앱 포트. 같은 서버의 인스턴스마다 10씩 벌린다 | 바꾸면 메인 서버 조각도 다시 넣어야 한다 |
| `EXTENSIONS` | 이 인스턴스가 켜는 확장 모듈, 쉼표로 | `sudo EXTENSIONS=hub,bom ./deploy.sh update` |
| `DOE_ROOT_HOST_DIR` | CAD(CompCore) 공용 폴더 — 아래 「DOE 공용 폴더」 | `sudo DOE_ROOT_HOST_DIR=… ./deploy.sh update` |
| `ANSYS_HOST_DIR` · `ANSYS_VERSION` | 리눅스 Ansys 설치 폴더 · 버전(기본 252) | 같은 방식 |
| `WORKER_COUNT` | 해석 작업 워커 수(기본 1) | 같은 방식 |

**이 표의 값은 전부 그 파일이 기억한다** — 한 번 주면 `update` 때 다시 안 붙여도 된다. 바꿀 때만
새 값을 붙인다. (v0.4.0 까지는 위의 새 세 줄을 기억하지 않아서 `update` 때 빠뜨리면 공용 폴더 · Ansys
연결이 **조용히 빠지고** 워커가 1 개로 줄었다.) 기억한 값은 `cat /etc/platform-instances/<slug>.conf`
로 본다. 연결을 **끊을** 때는 그 파일의 줄을 비우고 `sudo ./deploy.sh update` — 빈 env 는
「안 줬다」 와 구별되지 않아 기억한 값이 남는다.

같은 서버에 두 번째 인스턴스는 다른 `APP_SLUG` · `APP_PORT` 로 같은 명령을 한 번 더. 인스턴스가
여럿이면 `update` · `status` 에도 붙인다 — `sudo APP_SLUG=<slug> ./deploy.sh update`(안 붙이면 어느 것인지 묻는다).

### SSH 로만 붙는 서버라면 — 미리 알아 둘 다섯

이 스크립트들은 **서버 콘솔 앞에 앉아 있든 SSH 로 붙든 똑같이 돈다.** 다만 원격일
때만 걸리는 것이 다섯 있다.

| | |
| --- | --- |
| **`root` 로 바로 ssh 했다면** | 운영 계정을 알 수 없어 멈춘다(`sudo` 를 거치지 않아 `SUDO_USER` 가 없다). `OPERATOR=<계정> ./deploy.sh install` 로 준다 |
| **임시 비밀번호는 한 번만 찍힌다** | 세션이 끊기면 잃는다. `sudo ./deploy.sh install 2>&1 \| tee ~/install-<태그>.log` 로 받아 둔다 |
| **`setup` 은 묻는다 — TTY 가 없으면 멈춘다** | 원격 자동 설치는 값을 env 로 주고 `--yes`: `sudo SETUP_ROLE=1 APP_SLUG=simengbay DOE_ROOT_HOST_DIR=/mnt/exchange/CompCore ./deploy.sh setup --yes`. 묻는 대신 env(없으면 기본값)를 쓰고 무엇을 썼는지 찍는다. **역할(`SETUP_ROLE=A\|B\|1`)은 꼭 준다** — 기본값이 없다. 먼저 `setup --yes --plan` 으로 계획만 본다. 대기(B)가 A 에서 파일을 받는 단계는 ssh 키로만 된다(비밀번호를 칠 사람이 없다) |
| **`reset` 은 되묻는다** | `ssh <서버> 'sudo ./deploy.sh reset'` 은 TTY 가 없어 그 물음에서 실패한다. `ssh -t` 로 붙는다 |
| **`prepare` 는 apt 를 쓴다** | 서버가 우분투 저장소(또는 사내 미러)에 닿아야 한다. apptainer 는 번들에 동봉한 `.deb` 로 깔리므로 PPA 에 닿을 필요는 없다. 그래도 못 깔면 `prepare` 가 DB·폴더까지 만든 뒤 **무엇을 먼저 깔지 말하고 멈춘다** — 해결 뒤 `prepare` 를 다시 돌린다(앞 단계는 멱등하다) |

번들 전체를 한 줄로 밀어 넣는 것도 된다:

```bash
scp <slug>-<태그>.tar.gz <계정>@<서버>:~/ && \
  ssh -t <계정>@<서버> "tar xzf <slug>-<태그>.tar.gz && cd <slug>-<태그> && sudo ./deploy.sh"
```

인자 없는 `./deploy.sh` 는 **설치된 흔적을 보고 스스로 고른다** — 처음이면
`install`, 있으면 `update`. **처음이고 리눅스가 낯설면 `sudo ./deploy.sh setup`** — 물어보며
전부 한다([쉬운-설치.md](쉬운-설치.md)).

---

## 1. (최초 1회) 서버 준비

```bash
sudo ./deploy.sh prepare
```

apt 패키지(postgresql·python3-venv), **apptainer**, DB 역할과 데이터베이스, 설치 폴더를 만든다.
**멱등하다** — 다시 돌려도 이미 있는 것은 건드리지 않는다.

**apptainer 는 우분투 기본 저장소에 없다.** 그래서 `prepare` 는 이 순서로 찾는다:

1. 이미 깔려 있으면 그대로 쓴다.
2. **번들에 동봉한 `.deb`**(`apptainer_debs/` — 빌드가 받아 넣는다)가 있으면 그것을 깐다. **폐쇄망은 여기서 끝난다.**
3. 닿는 저장소(사내 미러 등)에 있으면 거기서 받는다.
4. 우분투면 **공식 PPA(`ppa:apptainer/ppa`)를 더해** 받는다 — CI 가 번들을 만들 때 쓰는 것과 같은 곳이다.

2 가 없는 옛 번들(v0.4.4 이전)이고 PPA 에도 닿지 않는 서버라면 `prepare` 가 **DB·폴더까지 만든 뒤** 멈추고
할 일을 말한다. 새 번들을 쓰거나, 닿는 PC 에서 `.deb` 를 받아 옮겨 깔고 다시 돌린다:

```bash
# 닿는 PC 에서: https://github.com/apptainer/apptainer/releases 의 amd64 .deb 를 받아
scp apptainer_*.deb <계정>@<서버>:~/

# 서버에서
sudo apt install ./apptainer_*.deb
sudo ./deploy.sh prepare      # 앞 단계는 이미 서 있어 건너뛴다
```

우분투가 아니면 PPA 를 쓸 수 없다 — https://apptainer.org/docs/admin/main/installation.html 대로
먼저 깔고 `prepare` 를 돌린다.

---

## 2. 설치

```bash
sudo ./deploy.sh install
```

하는 일:

1. `~/apps/<slug>/{filestore,logs}` 생성 (공용 스토리지 `DATA_DIR` 를 주면 첨부 · `.env` · 백업은 거기 — 「8. 이중화」)
2. `.env` 생성 — **JWT 비밀키를 난수로 만들고 DB 비밀번호를 돌린다**
   (이미 있으면 손대지 않는다. 덮으면 전원이 다시 로그인한다)
3. `app.sif` 배치
4. 마이그레이션 → 설치 시드
5. systemd 유닛 렌더 → `enable` → `start`
6. `/api/health` 확인

> 관리자 **임시 비밀번호가 화면에 한 번만** 찍힌다. 받아 적어 전달한다.
> 첫 로그인에서 변경이 강제된다.
>
> **SSH 로 붙어 있다면** 세션이 끊기는 것만으로 잃는다. 그때는 되찾을 길이
> `reset`(파괴적)뿐이다 — 그 계정이 유일한 관리자이기 때문이다.
> `sudo ./deploy.sh install 2>&1 | tee ~/install.log` 로 받아 두고, 전달한 뒤 지운다.

확인:

```bash
curl http://127.0.0.1:<포트>/api/health
sudo journalctl -u <slug> -f
# 해석 작업 워커 — 이것이 안 돌면 작업이 「대기」 에서 움직이지 않는다.
systemctl status '<slug>-worker@1'
```

**워커가 살아 있는지는 화면에서 본다** — 관리 → 서버의 「워커 · 솔버」 카드(v0.3.0). 워커마다
상태(기다림 · 작업 중 · 응답 없음) · 집는 솔버 · 깔린 도구(ccx · gmsh · Ansys) · 지금 하는 일,
솔버마다 대기 · 실행 중 · 집을 워커 수, 그리고 Ansys 라이선스를 쥔 작업이 보인다. **기다리는
작업이 있는데 그 솔버를 집는 워커가 없으면 맨 위에 빨갛게** 적힌다. 워커는 15초마다 신호를
적고, 2분 끊기면 「응답 없음」 이 되며 그 워커가 잡고 있던 작업은 다른 워커가 곧바로 되살린다
(신호를 안 적는 옛 워커의 작업은 전처럼 3시간 뒤).

### 솔버를 갈라 띄우기 — CalculiX 로 설계점을 동시에 풀려면

**Ansys 는 노드락 라이선스가 하나라 워커도 하나여야 한다.** CalculiX(오픈소스)는 라이선스가
없어 코어 수만큼 띄울 수 있다. 섞어 띄우면 CalculiX 를 늘리려다 **Ansys 작업이 라이선스 오류로
실패한다** — 그래서 워커마다 집을 솔버를 정한다:

```bash
cd ~/apps/<slug>
echo SIMULATION_SOLVERS=ansys    > worker-1.env     # 하나만
for i in 2 3 4; do echo SIMULATION_SOLVERS=calculix > worker-$i.env; done
sudo systemctl restart '<slug>-worker@*'
journalctl -u '<slug>-worker@2' -n 5    # 「솔버 calculix」 가 찍힌다
```

파일이 없는 워커는 **전부** 집는다(설정을 안 건드린 설치는 그대로 돈다). 워커 수 자체는
`WORKER_COUNT` 로 정한다(한 번 주면 기억한다).

**CalculiX 가 이미지에 있는지**는 서버 화면의 「워커 · 솔버」 카드(깔린 도구 — 워커가 기동 때
찾은 것)에서 보고, 셸에서는 이렇게 본다:

```bash
apptainer exec ~/apps/<slug>/app.sif ccx -v
apptainer exec ~/apps/<slug>/app.sif gmsh -info | head -3
```

없으면 그 서버에서는 CalculiX 를 고른 작업이 「솔버를 못 찾았다」 로 **즉시** 실패한다 —
조용히 다른 솔버로 풀지 않는다(`deploy/NOTICE`).

### DOE 공용 폴더 — CAD 가 내보낸 것을 읽으려면

CAD 플랫폼(CompCore)이 설계점 묶음(DOE) · 설계 하나를 폴더로 내보내고, 이 서버가 **그 폴더를
읽어** 해석을 건다 — 「새 해석 작업」 의 「CAD 폴더에서 선택」 과 「DOE 가져오기」 가 여기를 본다.
컨테이너는 걸어 준 폴더만 보므로 **한 번** 알려 준다(그 뒤로는 기억한다 — 위 표):

```bash
sudo DOE_ROOT_HOST_DIR=/mnt/exchange/CompCore ./deploy.sh update   # 설치 때라면 install
```

`install` · `update` 는 끝에 그 폴더를 **운영 계정으로 읽어 본다** — 읽히면 「CAD 공용 폴더 읽기
확인 … (폴더 N 개)」, 아니면 경고가 찍힌다. 나중에는 `sudo ./deploy.sh status` 의 「CAD 공용 폴더」
칸에서 같은 것을 본다.

**공유 스토리지(NAS)는 재부팅 뒤에도 붙어 있어야 한다** — `/etc/fstab` 에 `_netdev` 로 넣는다.
빠지면 증상은 「CAD 폴더에서 선택」 이 폴더를 못 읽는 것이고, 원인은 배포가 아니라 마운트다:

```bash
mount | grep exchange          # 아무것도 안 나오면 안 붙어 있다
# /etc/fstab 예 (NFS) — _netdev: 네트워크가 올라온 뒤에 붙인다
# nas01:/exchange  /mnt/exchange  nfs  defaults,_netdev  0  0
sudo mount -a && mount | grep exchange
```

| | |
| --- | --- |
| 무엇을 거나 | 호스트의 그 폴더 → 컨테이너의 `/data/doe`, **읽기 전용** |
| `.env` | `DOE_ROOTS=/data/doe` 를 자동으로 채운다(컨테이너 안에서 보는 경로) |
| 안 주면 | 「CAD 폴더에서 선택」 · DOE 가져오기가 「공용 폴더가 설정돼 있지 않습니다」 라고 말한다. 「파일 직접 업로드」 는 그대로 된다 |
| 권한 | **읽기만 하면 된다.** 가져올 때 STEP 을 작업 폴더로 복사하므로 원본은 손대지 않는다 |
| CAD 쪽과의 관계 | CompCore 의 `DOE_EXPORT_ROOT` 와 **같은 실제 폴더**여야 한다. 두 서버가 다른 기계면 공유 스토리지(NFS · SMB)를 양쪽에 마운트한다 — 경로 이름은 서로 달라도 된다 |

> **공유 스토리지가 없는 배치라면** 폴더로는 주고받을 수 없다. 그때는 CAD 쪽에 번들 내려받기
> API 를 두고 이 서버가 받아 오는 방식이 필요하다 — 아직 없다(정해지면 이 자리에 설정이 는다).

> **워커 수는 한 번 정하면 기억한다** — `sudo WORKER_COUNT=4 ./deploy.sh update`(기본 1).
> 워커 하나가 한 번에 작업 하나를 돌린다. 1.5단계에서 진짜 Mechanical 이 붙으면
> **라이선스 수를 넘기지 않는다** — 넘긴 워커는 라이선스 오류로 실패한다.
> 줄여서 다시 깔면 남는 인스턴스는 `deploy.sh` 가 내린다.

---

## 3. 갱신

```bash
# 새 번들을 풀고 그 안에서
sudo ./deploy.sh update
```

**스크립트도 새 번들의 것을 쓴다** — 옛 `deploy.sh` 로 새 SIF 를 깔면 그 릴리스가
기대하는 단계가 통째로 안 돌고, 안 돌았다는 사실은 아무 데도 안 적힌다. 번들
안에서 실행하면 저절로 그렇게 된다.

직전 이미지는 `app.sif.prev` 로 남는다. 롤백:

```bash
sudo systemctl stop <slug>
sudo mv ~/apps/<slug>/app.sif.prev ~/apps/<slug>/app.sif
sudo systemctl start <slug>
```

**파일만 되돌아간다 — 마이그레이션은 취소되지 않는다.** 파괴적 마이그레이션
(컬럼 삭제·이름 변경)을 적용했다면 DB 는 백업에서 따로 복구해야 한다.

---

## 4. 백업

```bash
./backup.sh -i ~/apps/<slug> -o ~/backup/<slug>
```

**DB 와 첨부를 같은 시각에 함께 받는다.** 둘 중 하나만 받으면 복구되지 않는다.

매일 받게 하려면 systemd 타이머로 건다 — `deploy.sh` 가 백업 폴더를 알면(`DATA_DIR`, 또는
`sudo BACKUP_HOST_DIR=<폴더> ./deploy.sh update`) `<slug>-backup.timer` 를 스스로 건다(매일 03:00,
이중화의 대기 서버는 03:30 — 그날 것이 이미 있으면 건너뛴다). 손으로 걸려면 `backup.sh` 머리말에
유닛 예시가 있다. **앱 프로세스에 넣지 않는다** — 앱이 죽은 날 백업도 조용히 죽는다.

그리고 `.env` 에 적어 둔다:

```
BACKUP_DIR=/home/<계정>/backup/<slug>
```

적어 두면 앱이 마지막 덤프 시각을 읽어 **36시간이 넘으면 홈의 「남은 일」 에
올린다.** 안 적으면 백업이 멈춘 것을 **복구가 필요한 날**에야 알게 된다.

### 한 번은 실제로 복구해 본다

```bash
./restore.sh -b ~/backup/<slug> -d <slug>_restore_check
```

받아만 두고 복구를 해 본 적이 없는 백업은 백업이 아니다. `restore.sh` 는 되돌린 뒤
**DB 가 가리키는 파일이 실제로 있는지 세어 본다** — 하나라도 없으면 거기서 멈춘다.

---

## 5. 초기화 (파괴적)

```bash
sudo ./deploy.sh reset
```

DB 를 지우고 다시 만들며 첨부도 지운다. `.env`·DB 역할·systemd 유닛은 남는다.
**DB 이름을 그대로 입력해야 진행된다.**

되묻는 자리가 있으므로 **원격에서는 `ssh -t`** 로 붙는다. 아니면 그 물음에서
읽기가 실패하고, 아무것도 안 지운 채 오류로 끝난다.

---

## 6. 한 서버에 여러 플랫폼

같은 번들의 인스턴스든 다른 제품군이든 **slug 하나로 전부 갈린다**:

| | 값 |
| --- | --- |
| 설치 경로 | `~/apps/<slug>` |
| 데이터베이스 · 역할 | `<slug>` |
| systemd 유닛 | `<slug>.service` · `<slug>-backup.timer` |
| 포트 | 설치 때 준 `APP_PORT` (없으면 `BUILD_INFO` 의 `port`) (플랫폼마다 10씩 벌린다) |

**slug 가 겹치면 서로를 덮어쓴다.** 유닛 이름이 같으면 나중 배포가 앞의 것을
그대로 지우고, 그 사실은 아무 데도 안 적힌다. 설치된 인스턴스는 `/etc/platform-instances/` 에
한 파일씩 있다 — 어느 것이 있는지는 `ls` 로 본다.

---

## 7. 겪게 될 것들

전부 **증상이 원인을 안 가리키는** 부류다.

| 증상 | 원인과 해결 |
| --- | --- |
| `apptainer: command not found` | `sudo ./deploy.sh prepare` — 공식 PPA 를 더해 깐다. 폐쇄망이면 `.deb` 로 먼저(1. 서버 준비) |
| `prepare` 가 `Unable to locate package apptainer` 로 멈춘다 | **v0.1.0 번들이다** — PPA 없이 apt 에서 찾았다. 새 번들로 다시 돌리거나 `sudo add-apt-repository -y ppa:apptainer/ppa && sudo apt-get update` 후 `prepare` 를 다시 |
| 서비스가 `failed` | `journalctl -u <slug> -n 50` |
| **파일 업로드에서 `Read-only file system`** | `.env` 의 `FILESTORE_DIR` 가 bind-mount 밖을 가리킨다. `/data/filestore` 여야 한다 |
| 모든 페이지가 JSON 404 | SIF 에 `frontend/dist` 가 없다. 라우팅 버그처럼 보이지만 아니다 |
| 운영이 development 로 뜬다 | `.env` 에 BOM 이 붙어 **첫 줄 키만 조용히 무시**됐다 |
| 기동 거부: `JWT_SECRET` | 기본값 그대로다. 그것이 의도다 — `.env` 에 난수를 넣는다 |
| `connection refused` (DB) | `systemctl status postgresql`, `.env` 의 포트 확인 |
| 화면이 500, 로그에 "없는 컬럼" | 마이그레이션이 안 돌았다. `sudo ./deploy.sh update` |
| **해석 작업이 「대기」 에서 안 움직인다** | 먼저 서버 화면의 「워커 · 솔버」 카드 — **그 솔버를 집는 워커가 있나**(CalculiX 작업인데 워커가 전부 `SIMULATION_SOLVERS=ansys` 면 영원히 대기한다). 워커가 아예 없으면 `systemctl status '<slug>-worker@1'` · `journalctl -u '<slug>-worker@1' -n 50`. 번들에 `worker.service.template` 이 없으면 설치가 건너뛴다(설치 로그에 「워커 유닛 건너뜀」) |
| **워커가 10초마다 다시 뜬다**(`journalctl` 에 `No module named app`) | v0.5.0 이하의 워커 유닛이 `/opt/app/backend` 로 옮기지 않고 띄웠다. v0.5.1 이상 번들로 `sudo ./deploy.sh update` — 유닛을 다시 그린다. 손으로 고친 유닛(`--pwd`)도 그때 덮이는데, 새 템플릿이 같은 일을 하므로 괜찮다. 지금은 install · update 끝에 「워커 N 이 떠 있지 않습니다」 와 마지막 기록이 찍힌다 |
| 해석 작업이 `license` 로 실패한다 | **Ansys** 워커 수가 Mechanical 라이선스 수보다 많다. 줄이려면 `sudo WORKER_COUNT=1 ./deploy.sh update` 로 낮추거나, 아래 「솔버를 갈라 띄우기」 로 Ansys 워커만 하나로 둔다 |
| **「CAD 폴더에서 선택」 · DOE 가져오기가 「공용 폴더가 설정돼 있지 않습니다」** | `DOE_ROOT_HOST_DIR` 를 한 번도 안 줬다. `sudo DOE_ROOT_HOST_DIR=… ./deploy.sh update` — 그 뒤로는 기억한다 |
| **어제까지 되던 「CAD 폴더에서 선택」 이 폴더를 못 읽는다** | 대개 NAS 가 빠졌다(재부팅 뒤 등). `mount \| grep exchange` — 비었으면 `/etc/fstab` 에 `_netdev` 로 넣고 `sudo mount -a`. `sudo ./deploy.sh status` 의 「CAD 공용 폴더」 칸도 같은 것을 본다. v0.4.0 이하에서 `update` 를 했다면 연결 자체가 빠졌을 수 있다 — 값을 다시 주고 `update` |
| DOE 화면에 「폴더가 없습니다」 | `.env` 의 `DOE_ROOTS` 가 **호스트 경로**를 가리킨다. 컨테이너 안에서 보이는 이름(`/data/doe`)이어야 한다 |
| 폴더는 보이는데 DOE 표시가 안 붙는다 | 그 폴더에 `manifest.csv` 가 없다 — CAD 가 내보내기를 끝내지 않았거나 상위 폴더를 보고 있다 |
| 포트가 이미 쓰인다 | 같은 서버의 다른 플랫폼과 겹쳤다. `ss -ltnp 'sport = :<포트>'` |
| 업로드 파일에 `Permission denied` | `sudo chown -R <계정>:<계정> ~/apps/<slug>/filestore` |
| **`bad interpreter: /usr/bin/env bash^M`** | 스크립트가 Windows 를 거치며 CRLF 가 됐다. 번들에서 푼 것을 그대로 쓴다(리눅스에서 만들어진다). 이미 섞였으면 `sed -i 's/\r$//' *.sh` |
| `운영 계정을 알 수 없습니다` | `root` 로 바로 ssh 했다. `OPERATOR=<계정> ./deploy.sh install` |
| `reset` 이 입력을 못 받고 끝난다 | TTY 가 없다. `ssh -t <계정>@<서버>` 로 붙는다 |
| 이중화: postgres 가 안 뜨고 로그에 `pg-ha:` | 옛 주가 주로 뜨려 했다(guard). `sudo ./deploy.sh db-standby --from <지금 주>` |
| 이중화: 화면이 `/<slug>/` 밑에서 API 404 | `.env` 에 `PUBLIC_PATH=/<slug>` 가 없거나 nginx 가 접두어를 안 뗐다. `sudo ./deploy.sh render` 로 설정을 본다 |
| 이중화: 로그인이 유지되지 않는다(새로고침마다 로그인) | `.env` 에 `REFRESH_COOKIE_SECURE=true` 가 있는데 http 로 들어왔다 — 지우거나 false 로(앱이 https 일 때 스스로 붙인다). 또는 `TRUST_PROXY` 가 꺼져 앱이 https 인 줄 모른다 |
| 이중화: B 의 `install` 이 「DB 는 대기입니다」 로 멈춘다 | `/data/…/.env` 가 없다 — A 에서 `install` 을 먼저 |
| 이중화: 대기의 복제가 `끊김` | 주의 pg_hba 에 대기 IP 가 없거나 `/etc/pg-ha.replpass` 가 다르다. 주에서 `db-primary` 다시 → 대기에서 `db-standby` |

### `.env` 를 고친 뒤에는

```bash
sudo systemctl restart <slug>
```

포트를 바꿨으면 그것으로 충분하다 — **Apptainer 는 호스트 네트워크를 그대로 쓴다**
(포트 매핑이 없다).

---

## 8. 이중화 — 서버 두 대 · 메인 서버 뒤 · 자동 전환

설계와 결정은 저장소의 `docs/이중화-배포-설계.md`. 여기는 **손으로 치는 순서**다.

```
사용자 · 외부 AI ──HTTPS──▶ 메인 서버 (포탈 + nginx — 메인 서버 쪽이 관리)
                              /<slug>/… → 접두어를 벗겨 A · B 로 분배
                         ┌──────────┴──────────┐
                    서버 A                  서버 B          둘 다 활성 (앱 :8070)
                    PostgreSQL 주 ── 복제 ──▶ 대기          DB VIP(있으면) 가 주를 따라간다
                         └──── /data/<slug>/ 공용 ────┘      첨부 · 백업 · .env
```

| 무엇이 어디에 | |
| --- | --- |
| 코드(SIF) · 로그 | 각 서버 `~/apps/<slug>` (`INSTALL_DIR`) |
| 첨부 · 백업 · `.env` · 복제 비밀번호 | `/data/<slug>/{filestore,backup,.env,db/}` (`DATA_DIR` — 경로는 env) |
| DB 원본 | 각 서버 로컬(`/var/lib/postgresql/16/main`) — `/data` 는 느려서 두지 않는다 |
| TLS · 로드밸런싱 · 접두어 벗기기 | **메인 서버의 nginx.** 우리는 넣어 달라고 할 조각(`~/apps/<slug>/main-server-nginx.conf`)을 만든다 |
| 호스트 수준 설정 | `/etc/platform-ha.conf` (역할 · 상대 IP · DB VIP · 호스트명) — 그 서버의 모든 플랫폼이 공유 |
| DB 주/대기 도구 | `/usr/local/sbin/pg-ha` (deploy.sh 가 깐다) · `/etc/pg-ha.conf` · `/etc/pg-ha.replpass` |

**운영 계정은 두 서버에서 같은 이름 · 같은 uid** 여야 한다 — `/data` 의 파일을 둘 다 읽고 써야 한다.

메인 서버가 없이 A · B 가 직접 받아야 하면 `LB_MODE=local WEB_VIP=<VIP>` — A · B 에 nginx + keepalived 웹 VIP + 자체 서명 인증서를 세운다(8.9).

### 8.1 최초 설치 — A(주) 먼저, 그다음 B

**가장 쉬운 길은 `setup` 이다.** 물음에 답하면 아래 단계를 순서대로 알아서 하고, 답한 값은
`/etc/platform-instances/<slug>.conf` · `/etc/platform-ha.conf` 에 남아 **다음부터는
`sudo ./deploy.sh update` 만** 치면 된다. 처음 하는 사람은 [번들의 「쉬운 설치」](쉬운-설치.md)를 본다.

```bash
# ── 서버 A ──   물음: 주(A) · 플랫폼 이름 · 화면 이름 · 포트 · 확장 · CAD 공용 폴더 · Ansys · B 의 IP · 호스트명 · 공용 폴더
sudo ./deploy.sh setup
# ── 서버 B ──   물음: 대기(B) · 플랫폼 이름 · CAD 공용 폴더 · Ansys · A 의 IP · 호스트명 · 공용 폴더 · A 의 계정
sudo ./deploy.sh setup           # A 에서 .env · 복제 비밀번호를 scp 로 받아 온다(A 계정 비밀번호를 한 번 묻는다)
```

`setup` 이 하는 것을 손으로 하면 이렇다(환경 변수 이름은 §0):

```bash
# ── 서버 A (주) ──
sudo APP_SLUG=<slug> APP_NAME=<이름> APP_PORT=<포트> EXTENSIONS=<확장> \
  HA_ROLE=master PEER_IP=<B의 IP> PUBLIC_HOST=<호스트명> DATA_DIR=/data/<slug> \
  ./deploy.sh prepare              # 패키지(postgresql-16 · keepalived) · DB 역할
sudo ./deploy.sh db-primary        # 복제 계정 · pg_hba · 감시 훅 · 원복 잠금. 비밀번호를 /data/…/db/ 에 둔다
sudo ./deploy.sh install           # .env(/data 에) · SIF · 마이그레이션 · 시드 · 유닛 · 메인 서버용 nginx 조각

# ── 서버 B (대기) ──  (같은 APP_* 값으로)
sudo APP_SLUG=<slug> APP_NAME=<이름> APP_PORT=<포트> EXTENSIONS=<확장> \
  HA_ROLE=backup PEER_IP=<A의 IP> PUBLIC_HOST=<호스트명> DATA_DIR=/data/<slug> \
  ./deploy.sh prepare
sudo ./deploy.sh db-standby        # A 에서 pg_basebackup — 기존 로컬 DB 는 옆으로 치운다
sudo ./deploy.sh install           # .env 는 /data 의 것을 그대로(만들지 않는다) · 마이그레이션은 이미 돼 있어 통과

# ── 메인 서버 쪽에 ──
cat ~/apps/<slug>/main-server-nginx.conf   # 이것을 그대로 넣어 달라고 한다

# 확인 (양쪽)
sudo ./deploy.sh status            # 앱 · 상대 앱 · 메인 서버 경유 health · pg-ha 역할 · 복제 지연 · VIP
```

**메인 서버 쪽에 부탁할 것** — 조각에 그대로 있다: `X-Forwarded-Proto $scheme` (앱이 https 인 줄 알아야 쿠키가 산다). 접두어 `/<slug>/` 는 벗겨 넘기든 그대로 넘기든 앱이 둘 다 받는다.

**메인 서버가 아직 없어도** A · B 설치와 8.3 · 8.4 의 리허설은 전부 된다 — 화면은 `http://<A의 IP>:8040/<slug>/` 로 직접 본다(접두어를 붙여서). http 로 직접 보는 동안은 쿠키에 Secure 가 안 붙을 뿐 로그인 유지는 된다.

DB VIP 가 있으면 A 의 첫 명령부터 `DB_VIP=<주소>` 를 함께 준다. **없으면** 앱은 A 의 IP 로 DB 에 붙고 자동 승격은 꺼진다 — 받은 뒤 「8.5」.

### 8.1b DB VIP 도 `/data` 도 아직 없을 때 — 리허설은 된다

| 없는 것 | 대신 |
| --- | --- |
| **DB VIP** | `DB_VIP` 를 안 주면 keepalived 도 자동 승격도 없다. 앱은 A 의 IP 로 DB 에 붙는다. 승격은 손으로(8.3 「DB VIP 없이」). guard 는 VIP 없이도 상대에게 물어 동작한다. 받으면 8.5 |
| **`/data/<slug>`** | `DATA_DIR` 를 안 주면 각 서버 `~/apps/<slug>` 에 전부 둔다. **B 의 `.env` 와 복제 비밀번호는 A 의 것**이어야 한다 — `setup` 이 A 의 `~/apps/<slug>/handoff/` 에서 scp 로 받아 온다(손으로 하면 `scp <A>:~/apps/<slug>/handoff/.env ~/apps/<slug>/.env`, 복제 비밀번호는 `/etc/pg-ha.replpass` 에 root:postgres 640). 첨부는 서버마다 따로 쌓인다(리허설이면 그것으로 충분). 나중에 `/data` 가 오면 `~/apps/<slug>/{.env,filestore}` 를 옮기고 `sudo DATA_DIR=/data/<slug> ./deploy.sh update` — 양쪽 |

리허설에서 볼 수 있는 것: 복제(`db-status` 의 지연), 손 승격 · demote · `db-standby` 재구성, guard(옛 주 부팅), 두 앱 동시 운영(동시 편집), B→A 업데이트, 재부팅. 못 보는 것: 자동 승격, 공용 첨부, 백업 폴더, 메인 서버 경유.

### 8.2 업데이트 — B 먼저, 그다음 A

```bash
# B 에서 (새 번들 안에서)
sudo ./deploy.sh update            # B 앱 중지 → SIF 교체 → 마이그레이션(주 DB 에 — 한 번만 돈다) → 기동
# A 에서
sudo ./deploy.sh update
```

한 대씩 하므로 **서비스는 끊기지 않는다** — 메인 서버의 nginx 가 멈춘 쪽을 빼고 보낸다(`max_fails=3`). 마이그레이션은 어느 서버에서 돌려도 주 DB 로 가고 두 번째는 할 일이 없다. 파괴적 마이그레이션(컬럼 삭제)은 옛 SIF 가 아직 도는 몇 분 동안 오류를 낼 수 있다 — 그런 릴리스는 두 대를 빠르게 잇달아 한다. 앱 포트 · slug 가 바뀌지 않는 한 메인 서버의 조각은 그대로다.

### 8.3 장애 — 무엇이 죽었나

| 죽은 것 | 저절로 | 사람이 |
| --- | --- | --- |
| **앱 한 대** | 메인 서버 nginx 가 3번 실패 뒤 뺀다. 살아나면 다시 넣는다 | `journalctl -u <slug>` |
| **서버 B(대기) 통째** | 아무 일도 없다. 복제만 멈춘다 | 살아나면 복제가 이어진다. `sudo ./deploy.sh db-status` 로 지연 확인. 오래 죽어 슬롯이 버려졌으면(`max_slot_wal_keep_size`) `db-standby` 로 다시 |
| **서버 A(주) 통째** | **DB VIP 가 있으면** 약 15초 뒤 B 가 승격되고 DB VIP → B. 마지막 몇 초의 쓰기는 유실될 수 있다. 앱은 B 만 남는다 | A 가 살아나도 **주로 못 뜬다**(guard). 「8.4」 대로 A 를 대기로 |
| **주 DB 만**(A 의 postgres) | 위와 같다(`pg-ha check` 가 3번 실패 → VIP 이동 → 승격) | 같다 |
| **DB VIP 없이 A 통째** | 앱은 B 만 남지만 **DB 를 잃는다** | B 에서 `sudo ./deploy.sh db-promote` → `/data/…/.env` 의 `DATABASE_URL` 호스트를 B 로 → `sudo systemctl restart <slug>` |
| **메인 서버** | 아무도 못 들어온다 — 메인 서버 쪽 일 | A · B 는 그대로 돈다. 급하면 `http://<A>:8040/<slug>/` 로 직접(접두어를 붙여서. http 라 리프레시 쿠키는 안 산다 — 확인용으로만) |
| **/data 가 안 보인다** | 첨부 · 백업이 멈춘다. 앱 재시작은 `.env` 를 못 읽어 실패한다(떠 있는 앱은 계속 돈다) | 마운트를 살린다. 그동안은 앱을 재시작하지 않는다 |

### 8.4 승격 뒤 원복 — 옛 주를 대기로, 그리고 (원하면) 다시 주로

승격된 채로 운영해도 된다 — **B 가 주인 것은 정상 상태다.** 필요한 것은 옛 주 A 를 대기로 돌려 다시 두 대가 되게 하는 것뿐이다.

```bash
# A 에서 — A 의 옛 데이터는 /var/lib/postgresql/16/main.old-<시각> 으로 옆에 남는다(한 벌만)
sudo ./deploy.sh db-standby --from <B의 IP>
sudo ./deploy.sh db-status        # 「대기 · streaming ← B」
```

굳이 A 를 다시 주로 하려면 **계획 전환** — 수십 초 중단, 유실 0:

```bash
# B(지금 주) 에서: 곱게 멈추고 「주 아님」 표시. 대기 A 가 남은 WAL 을 다 받는다
sudo ./deploy.sh db-demote
# A 에서: 승격. DB VIP 가 있으면 저절로 따라온다(check-primary)
sudo ./deploy.sh db-promote
# B 에서: A 의 대기로 재구성
sudo ./deploy.sh db-standby --from <A의 IP>
```

DB VIP 가 없을 때는 각 단계 사이에 `/data/…/.env` 의 `DATABASE_URL` 을 바꾸고 양쪽 앱을 재시작한다.

### 8.5 DB VIP 를 나중에 받았을 때

```bash
# 양쪽 모두
sudo DB_VIP=<주소> ./deploy.sh lb           # keepalived 에 DB VIP 인스턴스 · 감시 · 자동 승격
# 주 서버에서
sudo ./deploy.sh db-primary                  # /etc/pg-ha.conf 에 VIP 를 적는다(감시가 그것을 본다)
# /data/…/.env 의 DATABASE_URL 호스트를 VIP 로 → 양쪽 sudo systemctl restart <slug>
```

### 8.6 재부팅 점검

부팅 순서는 유닛이 정한다 — PostgreSQL → keepalived(그 뒤에 떠야 「아직 안 뜬 주」 를 죽었다고 보지 않는다) → 앱. 켠 뒤:

```bash
sudo ./deploy.sh status
```

- 「역할」 이 기대와 같은가(A 주 · B 대기). 옛 주가 guard 에 막혀 postgres 가 안 떴으면 `journalctl -u postgresql@16-main` 에 「pg-ha: …standby --from…」 이 있다 — 그대로 한다.
- DB VIP 가 주 DB 서버에 있나.
- 메인 서버 경유 health 가 200 인가.

### 8.7 스플릿 브레인 — 두 주가 되는 것을 막는 세 겹

1. **guard**(systemd `ExecStartPre`): 데이터 폴더가 「주」 모양인데 DB VIP 에서 다른 DB 가 응답하거나 상대가 주라고 답하면 postgres 를 **띄우지 않는다**.
2. **check-primary**: 내가 주라도 DB VIP 를 남이 쥐고 거기서 DB 가 응답하면 우선순위 +50 을 잃는다 — VIP 를 되찾지 못한다.
3. **demote 표시**(`/var/lib/pg-ha/demoted`): 계획 전환으로 내려온 주는 `db-standby` 전까지 안 뜬다.

셋 다 **주로 뜨는 것**만 막고 대기로 뜨는 것은 막지 않는다. 막혔을 때 할 일은 언제나 같다 — `db-standby --from <지금 주>`.

### 8.8 한 서버 두 대에 여러 플랫폼

`/etc/platform-ha.conf` · keepalived · PostgreSQL 주/대기는 **호스트에 하나**다. 두 번째 플랫폼(같은 번들의 다른 인스턴스든 다른 제품군이든)은 다른 `APP_SLUG` · `APP_PORT` 로 `prepare` → `install` 만 하면 메인 서버용 조각이 하나 더 생기고 같은 PostgreSQL 클러스터에 DB 하나가 더 생긴다(복제도 저절로 함께). `db-primary` · `db-standby` 는 **클러스터에 한 번**이면 된다 — 두 번째 플랫폼에서 다시 돌리면 pg_hba 만 갱신되고 같다.

### 8.9 메인 서버 없이 — A · B 가 직접 받을 때 (`LB_MODE=local`)

`LB_MODE=local WEB_VIP=<VIP>` 를 더해 8.1 을 그대로 하면 A · B 에 nginx(TLS 종단 · 접두어 벗기기 · 두 앱 분배)와 keepalived 웹 VIP(vrid 51, master 역할 서버가 쥔다)가 선다. 인증서는 A 가 자체 서명으로 만들어 `/data/…/tls/` 에 두고 B 가 가져간다. 정식 인증서를 받으면 두 서버의 `/etc/nginx/tls/server.{crt,key}` 를 바꾸고 `sudo systemctl reload nginx`.
