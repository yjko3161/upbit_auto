import sys
import time
import datetime
import traceback
import json
import os
import requests # Import requests for direct API call
import pandas as pd
import pyupbit
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QLineEdit, QPushButton, QTextEdit, 
    QGroupBox, QDoubleSpinBox, QMessageBox, QSplitter, QCheckBox,
    QComboBox, QCompleter
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPalette

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

class RSIWorker(QThread):
    """
    Background worker thread for trading logic to prevent GUI freezing.
    """
    # Signals to update GUI
    log_signal = pyqtSignal(str)
    # price, rsi, profit_rate, total_asset, signed_change_rate
    status_signal = pyqtSignal(float, float, float, float, float) 
    data_signal = pyqtSignal(pd.DataFrame) # New signal for Chart Data
    msg_signal = pyqtSignal(str) # Detailed status message

    def __init__(self):
        super().__init__()
        self.running = True  # Thread life cycle
        self.auto_active = False # Auto trading toggle
        self.simulation_mode = False # Mock trading
        
        # Default settings
        self.ticker = "KRW-BTC"
        self.rsi_period = 14
        self.roi_target = 0.5
        self.roi_stop = -3.0
        self.rsi_entry = 25.0
        self.amount = 100000.0
        self.access_key = ""
        self.secret_key = ""
        
        self.upbit = None
        
        # Simulation Wallet
        self.sim_balance_krw = 10000000.0 # 10 Million KRW virtual
        self.sim_balance_coin = 0.0
        self.sim_avg_buy_price = 0.0
        
        # Internal state
        self.avg_buy_price = 0.0
        self.balance = 0.0
        
        # Safety: Consecutive Loss Cooldown
        self.loss_count = 0
        self.max_loss_count = 0 # 0 means disabled, set via settings
        self.cooldown_minutes = 30
        self.cooldown_end_time = None

    def update_settings(self, ticker, rsi_entry, roi_target, roi_stop, amount, access, secret, simulation, max_loss, cooldown):
        self.ticker = ticker
        self.rsi_entry = rsi_entry
        self.roi_target = roi_target
        self.roi_stop = roi_stop
        self.amount = amount
        self.access_key = access
        self.secret_key = secret
        self.simulation_mode = simulation
        
        self.max_loss_count = max_loss
        self.cooldown_minutes = cooldown
        
        if not self.simulation_mode and self.access_key and self.secret_key:
            self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)

    def run(self):
        self.log_signal.emit(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Trading Thread Started.")
        
        while self.running:
            try:
                # Initialize variables to defaults or previous values to prevent '0' or UnboundLocalError
                current_price = 0.0
                rsi = 0.0
                profit_rate = 0.0
                total_asset = 0.0
                signed_change_rate = 0.0
                
                # 1. Fetch Price & RSI
                # Fetch minute candles for RSI
                try:
                    # Use direct API call for robustness
                    url = "https://api.upbit.com/v1/ticker"
                    resp = requests.get(url, params={"markets": self.ticker})
                    
                    if resp.status_code == 200:
                        data = resp.json()[0]
                        current_price = float(data['trade_price'])
                        signed_change_rate = float(data['signed_change_rate']) 
                    else:
                        # Fallback
                        cp = pyupbit.get_current_price(self.ticker)
                        if cp is not None:
                            current_price = float(cp)

                    df_candle = pyupbit.get_ohlcv(self.ticker, interval="minute1", count=200) 
                    if df_candle is not None:
                        # Do NOT overwrite current_price with candle close, ticker is more current
                        rsi = self._calculate_rsi_from_df(df_candle)
                    else:
                        rsi = 0.0
                        self.log_signal.emit(f"⚠️ 캔들 데이터 조회 실패: {self.ticker}")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ 캔들 API 오류: {e}")

                # 2. Calculate Asset & Profit
                if self.simulation_mode:
                    if self.sim_balance_coin > 0:
                        profit_rate = (current_price - self.sim_avg_buy_price) / self.sim_avg_buy_price * 100
                    total_asset = self.sim_balance_krw + (self.sim_balance_coin * current_price)
                elif self.upbit:
                    try:
                         balance = self.upbit.get_balance(self.ticker)
                         if balance is None: balance = 0
                         
                         avg_buy_price = self.upbit.get_avg_buy_price(self.ticker)
                         if avg_buy_price is None or avg_buy_price == 0:
                             profit_rate = 0.0
                         else:
                             if current_price > 0:
                                 profit_rate = ((current_price - avg_buy_price) / avg_buy_price) * 100
                             
                         total_asset = float(self.upbit.get_balance("KRW") or 0) + (balance * current_price)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ 잔고/수익률 조회 실패: {e}")
                
                # Report Status to GUI
                if current_price > 0:
                    self.status_signal.emit(current_price, rsi, profit_rate, total_asset, signed_change_rate)
                
                # Fetch Tick data for Chart
                try:
                    # Direct API call since pyupbit might lack this specific wrapper or naming differs
                    url = "https://api.upbit.com/v1/trades/ticks"
                    params = {"market": self.ticker, "count": 50}
                    response = requests.get(url, params=params)
                    
                    if response.status_code == 200:
                        ticks = response.json()
                        if ticks:
                            df_tick = pd.DataFrame(ticks)
                            # Data: trade_price, trade_volume, trade_timestamp, etc.
                            # Reverse to have oldest first
                            df_tick = df_tick.iloc[::-1]  
                            self.data_signal.emit(df_tick)
                    else:
                        pass
                except Exception as e:
                    self.log_signal.emit(f"⚠️ 체결 API 오류: {e}")

                # 2. Calculate Profit
                profit_rate = 0.0
                if self.simulation_mode:
                    if self.sim_balance_coin > 0:
                        profit_rate = (current_price - self.sim_avg_buy_price) / self.sim_avg_buy_price * 100
                elif self.upbit:
                    try:
                        avg_price = self.upbit.get_avg_buy_price(self.ticker)
                        if avg_price > 0:
                            profit_rate = (current_price - avg_price) / avg_price * 100
                    except:
                        pass 
                
                # Mocking profit calculation for display if we don't have real connection or assets yet
                # In a real bot, we would query self.upbit.get_balance(self.ticker) 
                # But to avoid rate limits in this loop, we do it sparingly or catch errors.
                
                # Report Status to GUI
                if current_price:
                    # Calculate Total Asset
                    total_asset = 0.0
                    if self.simulation_mode:
                        total_asset = self.sim_balance_krw + (self.sim_balance_coin * current_price)
                    elif self.upbit:
                        try:
                            krw = self.upbit.get_balance("KRW")
                            coin = self.upbit.get_balance(self.ticker)
                            total_asset = krw + (coin * current_price)
                        except:
                            pass
                            
                    self.status_signal.emit(current_price, rsi, profit_rate, total_asset, signed_change_rate)
                
                # 3. Auto Trading Logic
                if self.auto_active:
                    # Check Cooldown
                    if self.cooldown_end_time:
                        if datetime.datetime.now() < self.cooldown_end_time:
                            remain = self.cooldown_end_time - datetime.datetime.now()
                            # Format mm:ss
                            mm, ss = divmod(remain.seconds, 60)
                            msg = f"🧊 과열 방지(연속 손절): {mm}분 {ss}초 후 재개"
                            self.msg_signal.emit(msg)
                            time.sleep(1)
                            continue
                        else:
                            self.cooldown_end_time = None
                            self.loss_count = 0
                            self.msg_signal.emit("🔥 쿨타임 종료! 매매를 재개합니다.")

                    # Run if Upbit is connected OR if we are in Simulation Mode
                    if self.upbit or self.simulation_mode:
                        self._process_auto_trading(current_price, rsi)
                    elif not self.simulation_mode and not self.upbit:
                        pass

            except Exception as e:
                # self.log_signal.emit(f"Error: {str(e)}")
                # Don't spam logs on transient network errors
                pass

            time.sleep(1) # Interval

    def _calculate_rsi_from_df(self, df):
        try:
            delta = df['close'].diff(1)
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(window=14, min_periods=14).mean()
            avg_loss = loss.rolling(window=14, min_periods=14).mean()
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1]
        except:
            return 0.0

    # Old method removed/replaced logic above, keeping signature if needed or just removing it.
    # def _calculate_rsi(self, ticker, interval="minute1", count=200): ...

    def _process_auto_trading(self, current_price, rsi):
        try:
            # 0. Check Balance
            if self.simulation_mode:
                krw_balance = self.sim_balance_krw
                coin_balance = self.sim_balance_coin
                avg_buy_price = self.sim_avg_buy_price
                is_holding = coin_balance > 0
            else:
                krw_balance = self.upbit.get_balance("KRW")
                coin_balance = self.upbit.get_balance(self.ticker)
                avg_buy_price = self.upbit.get_avg_buy_price(self.ticker)
                
                # Use a threshold to determine if we are holding the coin (e.g. > 5000 KRW value)
                current_value = coin_balance * current_price
                is_holding = current_value >= 5000

            # 1. Buy Logic (If not holding)
            if not is_holding:
                if rsi <= self.rsi_entry:
                    if krw_balance >= self.amount:
                        if self.simulation_mode:
                            buy_amt = self.amount / current_price
                            self.sim_balance_coin += buy_amt
                            self.sim_balance_krw -= self.amount
                            self.sim_avg_buy_price = current_price
                            self.log_signal.emit(f"🧪 [SIM] 매수: {current_price} 원 (수량: {buy_amt:.8f})")
                        else:
                            self.upbit.buy_market_order(self.ticker, self.amount)
                            self.log_signal.emit(f"🚀 실전 매수 체결: RSI {rsi:.1f} <= {self.rsi_entry}")
                        
                        time.sleep(2)
                    else:
                        self.msg_signal.emit("⚠️ 잔고 부족 (KRW)")
                else:
                    self.msg_signal.emit(f"👀 관망중... 현재 RSI {rsi:.1f} > 목표 {self.rsi_entry}")

            # 2. Sell Logic (If holding)
            else:
                profit_rate = 0.0
                if avg_buy_price > 0:
                    profit_rate = (current_price - avg_buy_price) / avg_buy_price * 100
                    
                self.msg_signal.emit(f"✊ 보유중... {profit_rate:.2f}% (평단: {avg_buy_price:,.0f})")
                
                # Debug logging for Sell diagnosis (Temporary)
                # self.log_signal.emit(f"Debug: Hold={is_holding}, Avg={avg_buy_price}, Cur={current_price}, Rate={profit_rate:.2f}%, Stop={self.roi_stop}%")
                
                if avg_buy_price > 0:
                    # profit_rate already calculated above
                    
                    sell_signal = False
                    reason = ""
                    
                    # Take Profit
                    if profit_rate >= self.roi_target:
                        sell_signal = True
                        reason = f"💰 익절 성공: {profit_rate:.2f}%"
                    
                    # Stop Loss
                    elif profit_rate <= self.roi_stop:
                        sell_signal = True
                        reason = f"📉 손절 매도: {profit_rate:.2f}%"
                        
                        
                    if sell_signal:
                        if self.simulation_mode:
                            amount_sold_krw = coin_balance * current_price
                            self.sim_balance_krw += amount_sold_krw
                            self.sim_balance_coin = 0
                            self.sim_avg_buy_price = 0
                            self.log_signal.emit(f"🧪 [SIM] 매도 체결: {reason}")
                        else:
                            self.upbit.sell_market_order(self.ticker, coin_balance)
                            self.log_signal.emit(reason)
                        
                        # Update Consecutive Loss Logic
                        if profit_rate <= self.roi_stop:
                            self.loss_count += 1
                            self.log_signal.emit(f"⚠️ 연속 손절 {self.loss_count}회 누적 (제한: {self.max_loss_count}회)")
                            
                            if self.max_loss_count > 0 and self.loss_count >= self.max_loss_count:
                                self.cooldown_end_time = datetime.datetime.now() + datetime.timedelta(minutes=self.cooldown_minutes)
                                self.log_signal.emit(f"🥶 손절 제한 도달! {self.cooldown_minutes}분간 매매를 중단합니다.")
                        else:
                             # Reset on Profit
                             if self.loss_count > 0:
                                 self.log_signal.emit(f"🍀 익절 성공! 연속 손절 카운트 초기화.")
                             self.loss_count = 0
                             
                        time.sleep(2)
                    
        except Exception as e:
            self.log_signal.emit(f"오류 발생: {str(e)}")

    def buy_now(self):
        self.log_signal.emit(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🚨 수동 매수 시도 (Market Price)")
        
        try:
            # 1. Simulation Mode
            if self.simulation_mode:
                 # Fetch current price first
                 current_price = pyupbit.get_current_price(self.ticker)
                 if current_price:
                     buy_amt = self.amount / current_price
                     self.sim_balance_coin += buy_amt
                     self.sim_balance_krw -= self.amount
                     self.sim_avg_buy_price = current_price
                     self.log_signal.emit(f"🧪 [SIM] 수동 매수 완료: {current_price:,.0f} 원")
                 else:
                     self.log_signal.emit("⚠️ 가격 조회 실패")
            
            # 2. Real Trading
            elif self.upbit:
                balance = self.upbit.get_balance("KRW")
                if balance < self.amount:
                    self.log_signal.emit("⚠️ 원화 잔고 부족")
                    return
                    
                resp = self.upbit.buy_market_order(self.ticker, self.amount)
                if isinstance(resp, dict) and 'uuid' in resp:
                    self.log_signal.emit("🚀 실전 수동 매수 주문 완료")
                else:
                    self.log_signal.emit(f"⚠️ 주문 실패: {resp}")
            else:
                self.log_signal.emit("⚠️ API Key가 설정되지 않았습니다.")
                
        except Exception as e:
            self.log_signal.emit(f"매수 오류: {str(e)}")

    def sell_all(self):
        self.log_signal.emit(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🚨 비상 전량 매도 (Panic Sell)!")
        
        try:
            # 1. Simulation Mode
            if self.simulation_mode:
                current_price = pyupbit.get_current_price(self.ticker)
                if current_price:
                    amount_sold_krw = self.sim_balance_coin * current_price
                    self.sim_balance_krw += amount_sold_krw
                    self.sim_balance_coin = 0
                    self.sim_avg_buy_price = 0
                    self.log_signal.emit(f"🧪 [SIM] 전량 매도 완료 (평가금: {amount_sold_krw:,.0f} 원)")
            
            # 2. Real Trading
            elif self.upbit:
                balance = self.upbit.get_balance(self.ticker)
                if balance and balance > 0:
                    # Minimum order rule check done by Upbit API usually, but good to note
                    resp = self.upbit.sell_market_order(self.ticker, balance)
                    if isinstance(resp, dict) and 'uuid' in resp:
                        self.log_signal.emit("📉 실전 전량 매도 주문 완료")
                    else:
                        self.log_signal.emit(f"⚠️ 매도 실패: {resp}")
                else:
                    self.log_signal.emit("⚠️ 보유한 코인이 없습니다.")
            else:
                self.log_signal.emit("⚠️ API Key가 설정되지 않았습니다.")
                
        except Exception as e:
             self.log_signal.emit(f"매도 오류: {str(e)}")

class ChartWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.figure.patch.set_facecolor('#353535') # Match theme
        self.canvas = FigureCanvas(self.figure)
        self.layout.addWidget(self.canvas)
        
        self.ax1 = self.figure.add_subplot(111)
        self.ax1.set_facecolor('#252525')
        self.ax1.tick_params(axis='x', colors='white')
        self.ax1.tick_params(axis='y', colors='white')
        
    def update_chart(self, df):
        self.ax1.clear()
        if df is None or df.empty:
            return

        # Tick data has 'trade_price'
        if 'trade_price' in df.columns:
            prices = df['trade_price']
            # Using simple index for x-axis in tick chart as timestamps are irregular
            x_vals = range(len(prices))
            self.ax1.plot(x_vals, prices, color='#4CAF50', label='Price')
            self.ax1.set_title("실시간 체결 차트 (50 Tick)", color='white', fontproperties=font_prop)
        else:
             # Fallback for OHLCV
             self.ax1.plot(df.index, df['close'], color='#4CAF50', label='Price')
             self.ax1.set_title("실시간 1분봉 차트", color='white', fontproperties=font_prop)

        self.ax1.grid(True, color='#444')
        self.figure.tight_layout()
        self.canvas.draw()
        
# Load font for Korean support in Matplotlib
# Windows font path example
try:
    from matplotlib import font_manager, rc
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if os.path.exists(font_path):
        font = font_manager.FontProperties(fname=font_path).get_name()
        rc('font', family=font)
        font_prop = font_manager.FontProperties(fname=font_path)
    else:
        font_prop = None
except:
    font_prop = None

class AntiGravityBot(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("안티 그래비티 봇 (Upbit RSI Scalping)")
        self.setGeometry(100, 100, 1200, 700) # Wider window
        
        self.worker = RSIWorker()
        self.worker.log_signal.connect(self.append_log)
        self.worker.status_signal.connect(self.update_dashboard)
        self.worker.data_signal.connect(self.update_chart_data) # Connect chart signal
        self.worker.msg_signal.connect(self.update_status_msg) # Connect detailed status
        self.worker.start()

        self.init_ui()
        self.load_settings() # Load config on startup
        self.apply_theme()
        
        # Track initial asset for Cumulative Return calculation (Real Trading)
        # Managed via load_settings
        # self.real_start_asset is initialized in load_settings or set to None

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main Layout: Horizontal Split (Left+Center | Right)
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # --- Left Panel: Settings ---
        left_group = QGroupBox("매매 설정 (Configuration)")
        left_layout = QGridLayout()
        left_group.setLayout(left_layout)
        
        self.input_ticker = QComboBox()
        self.input_ticker.setEditable(True) # Allow searching/typing
        self.input_ticker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert) # Prevent adding new items
        
        # Enable substring matching (e.g. "비트" finds "비트코인")
        completer = QCompleter(self.input_ticker.model())
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.input_ticker.setCompleter(completer)
        
        try:
            # Fetch all markets with details
            url = "https://api.upbit.com/v1/market/all?isDetails=false"
            resp = requests.get(url)
            if resp.status_code == 200:
                markets = resp.json()
                krw_markets = [m for m in markets if m['market'].startswith("KRW-")]
                
                items = []
                for m in krw_markets:
                    name = f"{m['korean_name']} ({m['market']})"
                    items.append(name)
                
                self.input_ticker.addItems(items)
                # Helper: Refresh completer model if items added later
                # But here we add immediately, so usually fine.
            else:
                 tickers = pyupbit.get_tickers(fiat="KRW")
                 self.input_ticker.addItems(tickers)
        except:
            self.input_ticker.addItem("비트코인 (KRW-BTC)")
            
        self.input_rsi = QDoubleSpinBox()
        self.input_rsi.setRange(0, 100)
        self.input_rsi.setValue(25.0)
        
        self.input_roi_target = QDoubleSpinBox()
        self.input_roi_target.setRange(0, 1000)
        self.input_roi_target.setValue(0.5)
        self.input_roi_target.setSuffix(" %")
        
        self.input_roi_stop = QDoubleSpinBox()
        self.input_roi_stop.setRange(-100, 0)
        self.input_roi_stop.setValue(-3.0)
        self.input_roi_stop.setSuffix(" %")
        
        self.input_amount = QDoubleSpinBox()
        self.input_amount.setRange(5000, 100000000)
        self.input_amount.setValue(100000)
        self.input_amount.setSuffix(" 원")
        
        self.input_access = QLineEdit()
        self.input_access.setPlaceholderText("업비트 Access Key 입력")
        self.input_access.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.input_secret = QLineEdit()
        self.input_secret.setPlaceholderText("업비트 Secret Key 입력")
        self.input_secret.setEchoMode(QLineEdit.EchoMode.Password)

        # Safety Settings (New)
        self.input_max_loss = QDoubleSpinBox()
        self.input_max_loss.setRange(0, 10)
        self.input_max_loss.setValue(3)
        self.input_max_loss.setDecimals(0)
        self.input_max_loss.setSuffix(" 회 (0=Off)")
        
        self.input_cooldown = QDoubleSpinBox()
        self.input_cooldown.setRange(1, 1440) # 1 min ~ 24 hours
        self.input_cooldown.setValue(30)
        self.input_cooldown.setDecimals(0)
        self.input_cooldown.setSuffix(" 분")
        
        self.chk_simulation = QCheckBox("모의 투자 (Simulation)")
        self.chk_simulation.setChecked(False)
        self.chk_simulation.setStyleSheet("color: #FF9800; font-weight: bold;")
        
        row = 0
        left_layout.addWidget(QLabel("대상 코인:"), row, 0); left_layout.addWidget(self.input_ticker, row, 1); row+=1
        left_layout.addWidget(QLabel("RSI 진입:"), row, 0); left_layout.addWidget(self.input_rsi, row, 1); row+=1
        left_layout.addWidget(QLabel("익절 수익률:"), row, 0); left_layout.addWidget(self.input_roi_target, row, 1); row+=1
        left_layout.addWidget(QLabel("손절 수익률:"), row, 0); left_layout.addWidget(self.input_roi_stop, row, 1); row+=1
        left_layout.addWidget(QLabel("주문 금액:"), row, 0); left_layout.addWidget(self.input_amount, row, 1); row+=1
        
        # New Safety UI
        left_layout.addWidget(QLabel("연속 손절 제한:"), row, 0); left_layout.addWidget(self.input_max_loss, row, 1); row+=1
        left_layout.addWidget(QLabel("쿨타임(대기):"), row, 0); left_layout.addWidget(self.input_cooldown, row, 1); row+=1
        
        left_layout.addWidget(QLabel("Access Key:"), row, 0); left_layout.addWidget(self.input_access, row, 1); row+=1
        left_layout.addWidget(QLabel("Secret Key:"), row, 0); left_layout.addWidget(self.input_secret, row, 1); row+=1
        left_layout.addWidget(self.chk_simulation, row, 0, 1, 2); row+=1
        
        apply_btn = QPushButton("설정 적용 (Apply)")
        apply_btn.clicked.connect(self.update_worker_settings)
        left_layout.addWidget(apply_btn, row, 0, 1, 2)
        
        # --- Center Panel: Controls ---
        center_group = QGroupBox("제어 패널 (Control)")
        center_layout = QVBoxLayout()
        center_group.setLayout(center_layout)
        
        self.btn_toggle = QPushButton("자동 매매 시작 (Start)")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        self.btn_toggle.toggled.connect(self.toggle_trading)
        
        self.btn_buy = QPushButton("⚡ 즉시 매수 (Buy Now)")
        self.btn_buy.setStyleSheet("background-color: #2196F3; color: white;")
        self.btn_buy.clicked.connect(self.worker.buy_now)
        
        self.btn_sell = QPushButton("🚨 비상 전량 매도 (Panic Sell)")
        self.btn_sell.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.btn_sell.clicked.connect(self.worker.sell_all)
        
        # Status Message Label
        self.lbl_trade_status = QLabel("대기중...")
        self.lbl_trade_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_trade_status.setStyleSheet("color: yellow; font-weight: bold; font-size: 14px; margin-top: 10px;")

        center_layout.addWidget(self.btn_toggle)
        center_layout.addSpacing(10)
        center_layout.addWidget(self.btn_buy)
        center_layout.addWidget(self.btn_sell)
        center_layout.addWidget(self.lbl_trade_status)
        center_layout.addStretch()

        # --- Right Panel: Dashboard ---
        right_group = QGroupBox("대시보드 (Dashboard)")
        right_layout = QVBoxLayout()
        
        # Info Cards
        info_layout = QGridLayout()
        self.lbl_price = QLabel("0 원")
        self.lbl_rsi = QLabel("0.0")
        self.lbl_profit = QLabel("0.0 %")
        self.lbl_cumulative = QLabel("0.0 %") # New: Cumulative Return
        self.lbl_total = QLabel("0 원") # New Label for Total Asset
        
        font_big = QFont("Arial", 16, QFont.Weight.Bold)
        self.lbl_price.setFont(font_big)
        self.lbl_rsi.setFont(font_big)
        self.lbl_profit.setFont(font_big)
        self.lbl_cumulative.setFont(font_big)
        self.lbl_total.setFont(font_big)
        self.lbl_total.setStyleSheet("color: #4CAF50;") 
        
        info_layout.addWidget(QLabel("현재가:"), 0, 0); info_layout.addWidget(self.lbl_price, 0, 1)
        info_layout.addWidget(QLabel("실시간 RSI:"), 1, 0); info_layout.addWidget(self.lbl_rsi, 1, 1)
        info_layout.addWidget(QLabel("보유 수익률:"), 2, 0); info_layout.addWidget(self.lbl_profit, 2, 1)
        info_layout.addWidget(QLabel("누적 수익률:"), 3, 0); info_layout.addWidget(self.lbl_cumulative, 3, 1)        
        info_layout.addWidget(QLabel("총 자산(추정):"), 4, 0); info_layout.addWidget(self.lbl_total, 4, 1)
        
        right_layout.addLayout(info_layout)
        
        # Log Window
        right_layout.addWidget(QLabel("시스템 로그:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #222; color: #0f0; font-family: Consolas;")
        right_layout.addWidget(self.log_text)
        
        right_group.setLayout(right_layout)

        # Assemble Main Layout
        # Left container (Settings + Controls)
        left_container = QWidget()
        left_container_layout = QVBoxLayout()
        left_container_layout.addWidget(left_group)
        left_container_layout.addWidget(center_group)
        left_container.setLayout(left_container_layout)
        
        # Right container (Chart + Dashboard + Log)
        right_container = QWidget()
        right_container_layout = QVBoxLayout()
        
        # Add Chart
        self.chart_widget = ChartWidget()
        right_container_layout.addWidget(self.chart_widget, 2) # Chart takes 2/3 height
        
        # Add Dashboard
        right_container_layout.addWidget(right_group, 1) # Dashboard/Log takes 1/3 height
        
        right_container.setLayout(right_container_layout)
        
        # Splitter to resize width
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_container)
        splitter.addWidget(right_container)
        splitter.setSizes([300, 900])
        
        main_layout.addWidget(splitter)

    def apply_theme(self):
        # Dark Theme using QSS (Qt Style Sheets) for better visibility control
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #353535;
                color: #ffffff;
            }
            QGroupBox {
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QLabel {
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit, QDoubleSpinBox {
                background-color: #252525;
                color: #ffffff;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 3px;
                selection-background-color: #4CAF50;
            }
            QComboBox {
                background-color: #252525;
                color: #ffffff;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 3px;
                selection-background-color: #4CAF50;
            }
            QComboBox QAbstractItemView {
                background-color: #353535;
                color: #ffffff;
                selection-background-color: #4CAF50;
            }
            QTextEdit {
                background-color: #1e1e1e; 
                color: #00ff00; 
                border: 1px solid #444;
                font-family: Consolas, Monospace;
            }
            QPushButton {
                background-color: #555;
                color: white;
                border: 1px solid #444;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #666;
            }
            QPushButton:pressed {
                background-color: #444;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
        """)
        
    def update_worker_settings(self):
        # Extract 'KRW-BTC' from '비트코인 (KRW-BTC)'
        raw_text = self.input_ticker.currentText()
        if "(" in raw_text and ")" in raw_text:
            ticker = raw_text.split("(")[1].split(")")[0]
        else:
            ticker = raw_text
            
        rsi = self.input_rsi.value()
        target = self.input_roi_target.value()
        stop = self.input_roi_stop.value()
        amt = self.input_amount.value()
        access = self.input_access.text()
        secret = self.input_secret.text()
        is_sim = self.chk_simulation.isChecked()
        
        max_loss = int(self.input_max_loss.value())
        cooldown = int(self.input_cooldown.value())

        self.worker.update_settings(
            ticker, rsi, target, stop, amt, access, secret, is_sim, max_loss, cooldown
        )
        mode = "SIMULATION" if is_sim else "REAL"
        self.append_log(f"설정 업데이트 완료. 모드: {mode}, 코인: {ticker}")
        self.save_settings()

    def load_settings(self):
        config_path = "config.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                target_ticker = config.get("ticker", "KRW-BTC")
                index = self.input_ticker.findText(target_ticker)
                if index >= 0:
                    self.input_ticker.setCurrentIndex(index)
                else:
                    self.input_ticker.setCurrentText(target_ticker)
                    
                self.input_rsi.setValue(config.get("rsi", 25.0))
                self.input_roi_target.setValue(config.get("roi_target", 0.5))
                self.input_roi_stop.setValue(config.get("roi_stop", -3.0))
                self.input_amount.setValue(config.get("amount", 100000))
                self.input_access.setText(config.get("access_key", ""))
                self.input_secret.setText(config.get("secret_key", ""))
                self.chk_simulation.setChecked(config.get("simulation", True))
                
                # Load Safety Settings
                self.input_max_loss.setValue(config.get("max_loss", 3))
                self.input_cooldown.setValue(config.get("cooldown", 30))
                
                # Restore Simulation State
                self.worker.sim_balance_krw = config.get("sim_balance_krw", 10000000.0)
                self.worker.sim_balance_coin = config.get("sim_balance_coin", 0.0)
                self.worker.sim_avg_buy_price = config.get("sim_avg_buy_price", 0.0)
                
                # Restore Real Trading Start Asset (for Cumulative Return)
                self.real_start_asset = config.get("real_start_asset", None)
                
                self.append_log("Settings & State loaded from config.json")
                # Auto apply on load (Optional, but good for UX)
                self.update_worker_settings()
                
            except Exception as e:
                self.append_log(f"Failed to load settings: {e}")
                self.real_start_asset = None
        else:
             self.real_start_asset = None

    def save_settings(self):
        config = {
            "ticker": self.input_ticker.currentText(),
            "rsi": self.input_rsi.value(),
            "roi_target": self.input_roi_target.value(),
            "roi_stop": self.input_roi_stop.value(),
            "amount": self.input_amount.value(),
            "access_key": self.input_access.text(),
            "secret_key": self.input_secret.text(),
            "simulation": self.chk_simulation.isChecked(),
            
            # Save Safety Settings
            "max_loss": self.input_max_loss.value(),
            "cooldown": self.input_cooldown.value(),
            
            # Save Simulation State
            "sim_balance_krw": self.worker.sim_balance_krw,
            "sim_balance_coin": self.worker.sim_balance_coin,
            "sim_avg_buy_price": self.worker.sim_avg_buy_price,
            
            # Save Real Trading Start Asset
            "real_start_asset": self.real_start_asset
        }
        try:
            with open("config.json", 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            self.append_log("Settings saved to config.json")
        except Exception as e:
             self.append_log(f"Failed to save settings: {e}")

    def toggle_trading(self, checked):
        self.worker.auto_active = checked
        if checked:
            self.btn_toggle.setText("매매 실행중... (중지하려면 클릭)")
            self.btn_toggle.setStyleSheet("background-color: #f44336; color: white;")
            self.append_log("자동 매매가 시작되었습니다.")
        else:
            self.btn_toggle.setText("자동 매매 시작 (Start)")
            self.btn_toggle.setStyleSheet("background-color: #4CAF50; color: white;")
            self.append_log("자동 매매가 중지되었습니다.")

    @pyqtSlot(str)
    def append_log(self, msg):
        self.log_text.append(msg)
        
    @pyqtSlot(pd.DataFrame)
    def update_chart_data(self, df):
        self.chart_widget.update_chart(df)

    @pyqtSlot(float, float, float, float, float)
    def update_dashboard(self, price, rsi, profit, total_asset, change_rate):
        # Current Price with Color
        # Dynamic Decimal Places
        if price < 1:
            price_str = f"{price:,.4f}" # e.g. 0.0061
        elif price < 100:
            price_str = f"{price:,.2f}" # e.g. 12.50
        else:
            price_str = f"{price:,.0f}" # e.g. 1,000
            
        self.lbl_price.setText(f"{price_str} 원")
        if change_rate > 0:
            self.lbl_price.setStyleSheet("color: #eb4034;") # Red (Rise upbit style)
        elif change_rate < 0:
            self.lbl_price.setStyleSheet("color: #1261c4;") # Blue (Fall)
        else:
            self.lbl_price.setStyleSheet("color: white;")
            
        self.lbl_rsi.setText(f"{rsi:.1f}")
        self.lbl_total.setText(f"{total_asset:,.0f} 원") # Update Total Asset
        
        # Color coding RSI
        if rsi <= 30: 
            self.lbl_rsi.setStyleSheet("color: #0f0;") # Green for oversold
        elif rsi >= 70:
             self.lbl_rsi.setStyleSheet("color: #f00;") # Red for overbought
        else:
            self.lbl_rsi.setStyleSheet("color: white;")
            
        self.lbl_profit.setText(f"{profit:+.2f} %")
        if profit > 0:
            self.lbl_profit.setStyleSheet("color: #0f0;")
        elif profit < 0:
            self.lbl_profit.setStyleSheet("color: #f00;")
        else:
            self.lbl_profit.setStyleSheet("color: white;")

        # Cumulative Return Calculation
        if self.worker.simulation_mode:
            start_asset = 10000000.0 # Fixed 10M for Sim
        else:
            # For Real, set baseline on first valid update if not exists
            if (self.real_start_asset is None or self.real_start_asset == 0) and total_asset > 0:
                self.real_start_asset = total_asset
                # Optional: Save immediately so we don't lose baseline on crash
                # self.save_settings() 
                
            start_asset = self.real_start_asset if self.real_start_asset else total_asset
            
        if start_asset and start_asset > 0:
            cum_rate = (total_asset - start_asset) / start_asset * 100
        else:
            cum_rate = 0.0
            
        self.lbl_cumulative.setText(f"{cum_rate:+.2f} %")
        if cum_rate > 0:
            self.lbl_cumulative.setStyleSheet("color: #0f0;")
        elif cum_rate < 0:
            self.lbl_cumulative.setStyleSheet("color: #f00;")
        else:
            self.lbl_cumulative.setStyleSheet("color: white;")

    @pyqtSlot(str)
    def update_status_msg(self, msg):
        self.lbl_trade_status.setText(msg)

    def closeEvent(self, event):
        """Save settings and state on app close"""
        self.save_settings()
        self.worker.running = False
        self.worker.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AntiGravityBot()
    window.show()
    sys.exit(app.exec())
