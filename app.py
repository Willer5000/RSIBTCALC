from flask import Flask, render_template, jsonify, request
import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime
import plotly.graph_objs as go
import threading
import os
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Top 60 criptomonedas por capitalización
symbols = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 
    'XRP/USDT', 'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT',
    'DOT/USDT', 'LINK/USDT', 'MATIC/USDT', 'SHIB/USDT',
    'LTC/USDT', 'UNI/USDT', 'ATOM/USDT', 'XLM/USDT',
    'ETC/USDT', 'FIL/USDT', 'APT/USDT', 'ARB/USDT',
    'NEAR/USDT', 'OP/USDT', 'VET/USDT', 'QNT/USDT',
    'RUNE/USDT', 'ALGO/USDT', 'GRT/USDT', 'AAVE/USDT',
    'AXS/USDT', 'XTZ/USDT', 'STX/USDT', 'EGLD/USDT',
    'THETA/USDT', 'EOS/USDT', 'FLOW/USDT', 'SAND/USDT',
    'MANA/USDT', 'APE/USDT', 'CRV/USDT', 'KAVA/USDT',
    'IMX/USDT', 'RNDR/USDT', 'MINA/USDT', 'MKR/USDT',
    'SNX/USDT', 'COMP/USDT', 'ZEC/USDT', 'DASH/USDT',
    'ENJ/USDT', 'IOTA/USDT', 'KSM/USDT', 'XMR/USDT',
    'NEO/USDT', 'GALA/USDT', 'CHZ/USDT', 'LDO/USDT',
    'WAVES/USDT', 'ROSE/USDT', 'ONE/USDT', 'HNT/USDT'
]

# Configuración de exchange con dominio alternativo
exchange = ccxt.binance({
    'enableRateLimit': True,
    'timeout': 30000,
    'urls': {
        'api': {
            'public': 'https://api.binance.me/api/v3'  # Dominio alternativo
        }
    }
})

# Variables globales
rsi_data = pd.DataFrame()
last_update_time = datetime.utcnow()
data_lock = threading.Lock()

current_config = {
    'timeframe': ('15m', '1h'),
    'volume_filter': 'Todas',
    'rsi_period': 14,
    'lower_x': 30,
    'upper_x': 70,
    'lower_y': 30,
    'upper_y': 70
}

# Funciones de cálculo
def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def fetch_ohlcv(symbol, timeframe, lookback=30):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=lookback)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])
        df['close'] = df['close'].astype(float)
        df['vol'] = df['vol'].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {symbol} {timeframe}: {str(e)[:100]}")
        time.sleep(1)
        return None

def calculate_volume_category(volumes):
    if len(volumes) == 0:
        return []
    high_thresh = np.percentile(volumes, 70)
    low_thresh = np.percentile(volumes, 30)
    return ['Alto' if vol >= high_thresh else 'Bajo' if vol <= low_thresh else 'Medio' for vol in volumes]

def fetch_all_data():
    global rsi_data, last_update_time
    
    print("Iniciando actualización de datos...")
    start_time = time.time()
    rsi_results = []
    volume_results = []
    
    try:
        # Obtener datos para BTC primero
        btc_data = {}
        volume_set = False  # Bandera para controlar si se estableció el volumen
        
        for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
            df = fetch_ohlcv('BTC/USDT', tf)
            if df is not None:
                btc_data[tf] = compute_rsi(df['close'], period=current_config['rsi_period']).iloc[-1]
                if tf == '1h':
                    btc_data['volume'] = df['vol'].mean()
                    volume_set = True
        
        btc_data['symbol'] = 'BTC/USDT'
        rsi_results.append(btc_data)
        
        # Solo agregar volumen si se estableció
        if volume_set:
            volume_results.append(btc_data['volume'])
        else:
            print("Advertencia: No se pudo obtener volumen para BTC/USDT")
    except Exception as e:
        print(f"Error procesando BTC: {e}")
    
    # Obtener datos para altcoins
    for sym in symbols:
        if sym == 'BTC/USDT':
            continue
            
        try:
            asset_data = {}
            volume_set = False
            timeframes = set(['15m', '30m', '1h', '2h', '4h', '1d', '1w'])
            
            for tf in timeframes:
                df = fetch_ohlcv(sym, tf)
                if df is not None:
                    asset_data[tf] = compute_rsi(df['close'], period=current_config['rsi_period']).iloc[-1]
                    if tf == '1h':
                        asset_data['volume'] = df['vol'].mean()
                        volume_set = True
                time.sleep(0.1)
            
            asset_data['symbol'] = sym
            rsi_results.append(asset_data)
            
            if volume_set:
                volume_results.append(asset_data['volume'])
            else:
                print(f"Advertencia: No se pudo obtener volumen para {sym}")
        except Exception as e:
            print(f"Error procesando {sym}: {e}")
    
    if rsi_results:
        df = pd.DataFrame(rsi_results)
        if len(volume_results) > 0:
            df['volume_cat'] = calculate_volume_category(volume_results)
        else:
            df['volume_cat'] = ['Medio'] * len(rsi_results)
            print("Advertencia: Usando categorías de volumen por defecto")
        
        # Asegurar que BTC está presente
        if 'BTC/USDT' not in df['symbol'].values:
            btc_row = pd.DataFrame([{
                'symbol': 'BTC/USDT',
                'volume_cat': 'Alto',
                **{tf: 50 for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']}
            }])
            df = pd.concat([df, btc_row], ignore_index=True)
        
        with data_lock:
            rsi_data = df
            last_update_time = datetime.utcnow()
    
    elapsed = time.time() - start_time
    print(f"Datos actualizados en {elapsed:.2f} segundos")
    print(f"Criptos obtenidas: {len(rsi_results)}/{len(symbols)}")
    return True

def create_plot():
    with data_lock:
        plot_data = rsi_data.copy()
        config = current_config.copy()
        last_update = last_update_time
    
    if plot_data.empty:
        fig = go.Figure()
        fig.add_annotation(text="Cargando datos...", x=0.5, y=0.5, showarrow=False, font=dict(size=24))
        return fig
    
    # Filtrar datos
    if config['volume_filter'] != 'Todas':
        plot_data = plot_data[plot_data['volume_cat'] == config['volume_filter']]
    
    # Asegurar BTC está presente
    btc_row = plot_data[plot_data['symbol'] == 'BTC/USDT']
    if not btc_row.empty and 'BTC/USDT' not in plot_data['symbol'].values:
        plot_data = pd.concat([plot_data, btc_row])
    
    # Obtener ejes
    x_time, y_time = config['timeframe']
    
    # Crear trazas
    traces = []
    for i, row in plot_data.iterrows():
        symbol = row['symbol']
        color = 'gold' if symbol == 'BTC/USDT' else \
                'green' if row['volume_cat'] == 'Alto' else \
                'blue' if row['volume_cat'] == 'Medio' else 'red'
        
        size = 50 if symbol == 'BTC/USDT' else 30
        name = symbol.split('/')[0]
        
        if symbol == 'BTC/USDT':
            textfont = dict(size=18, color='darkorange', family='Arial', weight='bold')
        else:
            textfont = dict(size=14, color='black', weight='bold')
        
        traces.append(go.Scatter(
            x=[row[x_time]],
            y=[row[y_time]],
            mode='markers+text',
            marker=dict(
                size=size,
                color=color,
                line=dict(width=2, color='black')
            ),
            text=name,
            textposition='top center',
            textfont=textfont,
            name=name,
            hoverinfo='text',
            hovertext=f"{name}<br>RSI {x_time}: {row[x_time]:.2f}%<br>RSI {y_time}: {row[y_time]:.2f}%<br>Volumen: {row['volume_cat']}"
        ))
    
    # Crear figura
    fig = go.Figure(data=traces)
    
    # Añadir líneas de referencia
    fig.add_shape(type="line", x0=config['lower_x'], y0=0, x1=config['lower_x'], y1=100,
                  line=dict(color="Green", width=3, dash="dash"))
    fig.add_shape(type="line", x0=config['upper_x'], y0=0, x1=config['upper_x'], y1=100,
                  line=dict(color="Red", width=3, dash="dash"))
    fig.add_shape(type="line", x0=0, y0=config['lower_y'], x1=100, y1=config['lower_y'],
                  line=dict(color="Green", width=3, dash="dash"))
    fig.add_shape(type="line", x0=0, y0=config['upper_y'], x1=100, y1=config['upper_y'],
                  line=dict(color="Red", width=3, dash="dash"))
    
    # Añadir zonas
    fig.add_hrect(
        y0=config['upper_y'], y1=100,
        line_width=0, fillcolor="red", opacity=0.15
    )
    fig.add_hrect(
        y0=0, y1=config['lower_y'],
        line_width=0, fillcolor="green", opacity=0.15
    )
    fig.add_vrect(
        x0=config['upper_x'], x1=100,
        line_width=0, fillcolor="red", opacity=0.15
    )
    fig.add_vrect(
        x0=0, x1=config['lower_x'],
        line_width=0, fillcolor="green", opacity=0.15
    )
    
    # Configurar layout
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M (UTC)")
    title = f"RSI ({config['timeframe'][0]} vs {config['timeframe'][1]}) | Período: {config['rsi_period']} | Filtro: {config['volume_filter']}"
    
    fig.update_layout(
        title=dict(text=f"{title}<br>{now}", font=dict(size=24)),
        xaxis_title=f"RSI {config['timeframe'][0]} (Límites: {config['lower_x']}/{config['upper_x']})",
        yaxis_title=f"RSI {config['timeframe'][1]} (Límites: {config['lower_y']}/{config['upper_y']})",
        xaxis=dict(
            range=[0, 100],
            tickmode='array',
            tickvals=list(range(0, 101, 10)),
            ticktext=[f"{x}%" for x in range(0, 101, 10)],
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=False,
            tickfont=dict(size=14)
        ),
        yaxis=dict(
            range=[0, 100],
            tickmode='array',
            tickvals=list(range(0, 101, 10)),
            ticktext=[f"{y}%" for y in range(0, 101, 10)],
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=False,
            tickfont=dict(size=14)
        ),
        template="plotly_white",
        showlegend=False,
        height=800,
        margin=dict(l=80, r=80, b=100, t=120, pad=20)
    )
    
    return fig

# Ruta principal
@app.route('/')
def index():
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    return render_template('index.html', graph_html=graph_html, 
                           current_config=current_config,
                           last_update=last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC"))

# API para actualizar configuración
@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.get_json()
    param = data.get('param')
    value = data.get('value')
    
    # Mapa de timeframes
    timeframe_map = {
        '15m_1h': ('15m', '1h'),
        '30m_2h': ('30m', '2h'),
        '1h_4h': ('1h', '4h'),
        '4h_1d': ('4h', '1d'),
        '1d_1w': ('1d', '1w')
    }
    
    with data_lock:
        config = current_config.copy()
        
        if param == 'timeframe':
            config['timeframe'] = timeframe_map.get(value, ('15m', '1h'))
        elif param == 'volume_filter':
            config['volume_filter'] = value
        elif param == 'period':
            config['rsi_period'] = int(value)
        elif param == 'lower_x':
            config['lower_x'] = int(value)
        elif param == 'upper_x':
            config['upper_x'] = int(value)
        elif param == 'lower_y':
            config['lower_y'] = int(value)
        elif param == 'upper_y':
            config['upper_y'] = int(value)
        
        # Actualizar config global
        current_config.update(config)
    
    # Forzar recálculo si se cambió periodo o timeframe
    if param in ['timeframe', 'period']:
        fetch_all_data()
    
    # Crear nuevo gráfico
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs=False)
    
    return jsonify({
        'success': True,
        'graph_html': graph_html,
        'last_update': last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    })

# Programar actualizaciones periódicas con reintentos
scheduler = BackgroundScheduler()
scheduler.add_job(
    fetch_all_data, 
    'interval', 
    minutes=5,
    max_instances=2,  # Permitir 2 instancias simultáneas
    misfire_grace_time=300  # Tolerancia de 5 minutos
)

# Iniciar la aplicación
if __name__ == '__main__':
    # Carga inicial de datos
    fetch_all_data()
    
    # Iniciar scheduler
    scheduler.start()
    
    # Obtener puerto de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
