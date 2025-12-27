# Anti-Gravity Bot (안티 그래비티 봇) - Upbit Scalping GUI

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green) ![Upbit](https://img.shields.io/badge/Exchange-Upbit-informational)

**Anti-Gravity Bot**은 업비트(Upbit) API를 활용한 데스크톱 기반의 RSI 역추세 매매(스캘핑) 프로그램입니다.  
파이썬 `PyQt6`를 사용하여 직관적인 GUI를 제공하며, `QThread`를 활용한 비동기 설계를 통해 끊김 없는 매매 환경을 지원합니다.

---

## 🚀 주요 기능 (Key Features)

### 1. 🧪 모의 투자 모드 (Simulation Mode) [NEW]
- **Simulate Checkbox**: 실제 자금을 사용하지 않고 전략을 검증할 수 있는 '모의 투자(Paper Trading)' 기능을 지원합니다.
- **가상 지갑**: 시뮬레이션 활성화 시 가상의 1,000만원 KRW가 지급되며, 실시간 시세에 맞춰 가상 매매가 이루어집니다.
- **시각적 구분**: 모의 투자 로그는 `🧪 [SIM]` 태그가 붙어 실전 매매와 명확히 구분됩니다.

### 2. 💾 설정 자동 저장 (Auto-Save Configuration) [NEW]
- **영구 보존**: API Key, 타겟 코인, RSI 설정값 등 사용자가 설정한 모든 환경이 `config.json` 파일에 자동 저장됩니다.
- **자동 불러오기**: 프로그램을 재시작하면 마지막으로 사용했던 설정이 자동으로 로드되어 번거로운 입력 과장이 사라집니다.

### 3. 직관적인 GUI 제어 (User-Friendly Interface)
- **실시간 설정 변경**: 코드를 수정하지 않고도 프로그램 실행 중에 **RSI 진입가, 익절률, 손절률, 주문 금액**을 즉시 변경할 수 있습니다.
- **상태 모니터링**: 현재가, 실시간 RSI, 보유 코인의 수익률을 한눈에 확인할 수 있는 대시보드를 제공합니다.

### 4. 안전한 비동기 설계 (Non-Blocking Architecture)
- **스레드 분리**: 매매 로직이 별도의 `QThread` 백그라운드 워커에서 동작하여, UI가 멈추거나 응답 없는 현상이 발생하지 않습니다.

### 5. 강력한 안전장치 (Safety Mechanisms)
- **Panic Sell (전량 매도)**: 비상 상황 시 버튼 클릭 한 번으로 보유 물량을 즉시 시장가로 정리합니다.
- **Stop Loss (자동 손절)**: 설정한 손실률에 도달하면 감정 개입 없이 기계적으로 손절합니다.

---

## 🛠 설치 및 실행 방법 (Installation & Usage)

### 1. 가상 환경 설정 및 라이브러리 설치
이 프로젝트는 독립된 실행 환경을 위해 Python 가상 환경(`venv`) 사용을 권장합니다.

```bash
# 1) 가상 환경 생성
python -m venv venv

# 2) 가상 환경 활성화
# Windows:
.\venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 3) 필수 라이브러리 설치
pip install -r requirements.txt
```

### 2. 프로그램 실행

```bash
python antigravity_bot.py
```

### 3. 사용 가이드
1.  **모드 선택**: 실전 투자를 하려면 [Simulate] 체크를 해제하고, 전략을 테스트하려면 체크하십시오.
2.  **API Key 설정**: (실전 모드 시) 좌측 패널에 업비트 API Access Key와 Secret Key를 입력합니다.
3.  **매매 옵션 설정**: 
    -   **Target Coin**: 거래할 코인 티커 (예: KRW-BTC)
    -   **RSI Entry**: 진입 기준 RSI (권장: 25~30 이하)
    -   **Take Profit**: 목표 수익률 (%)
    -   **Order Amt**: 1회 주문 금액 (KRW)
4.  **적용**: [Apply Settings] 버튼을 눌러 설정을 저장합니다. (자동으로 `config.json`에 저장됨)
5.  **시작**: [Start Auto Trading] 버튼을 눌러 매매를 시작합니다.

---

## 📁 파일 구조
-   `antigravity_bot.py`: 프로그램 실행 메인 파일
-   `config.json`: 사용자 설정 저장 파일 (자동 생성)
-   `requirements.txt`: 필수 라이브러리 목록

---

## ⚠️ 주의사항 (Disclaimer)
-   API Key는 사용자 PC의 `config.json`에만 저장되며 외부로 전송되지 않습니다.
-   본 프로그램은 투자를 보조하는 도구이며, 이로 인한 손실에 대해 개발자는 책임을 지지 않습니다.
