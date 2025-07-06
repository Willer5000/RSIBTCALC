from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import plotly.graph_objs as go
import threading
import os
import requests
import json
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Top 60 criptomonedas por capitalización
symbols = [
    'bitcoin', 'ethereum', 'binancecoin', 'solana', 
    'ripple', 'cardano', 'dogecoin', 'avalanche-2',
    'polkadot', 'chainlink', 'matic-network', 'shiba-inu',
    'litecoin', 'uniswap', 'cosmos', 'stellar',
    'ethereum-classic', 'filecoin', 'aptos', 'arbitrum',
    'near', 'optimism', 'vechain', 'quant-network',
    'thorchain', 'algorand', 'the-graph', 'aave',
    'axie-infinity', 'tezos', 'stacks', 'elrond-erd-2',
    'theta-token', 'eos', 'flow', 'the-sandbox',
    'decentraland', 'apecoin', 'curve-dao-token', 'kava',
    'immutable-x', 'render-token', 'mina-protocol', 'maker',
    'havven', 'compound-governance-token', 'zcash', 'dash',
    'enjincoin', 'iota', 'kusama', 'monero',
    'neo', 'gala', 'chiliz', 'lido-dao',
    'waves', 'oasis-network', 'harmony', 'helium'
]

# Fuente de datos alternativa
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Variables globales
rsi_data = pd.DataFrame()
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
cached_data = None

current_config = {
    'timeframe': ('15m', '1h'),
    'volume_filter': 'Todas',
    'rsi_period': 14,
    'lower_x': 30,
    'upper_x': 70,
    'lower_y': 30,
    'upper_y': 70
}

# Cargar datos de caché desde archivo
def load_cache():
    global cached_data
    try:
        with open('data_cache.json', 'r') as f:
            cached_data = json.load(f)
        print("Datos de caché cargados exitosamente")
    except:
        print("No se encontró caché, creando nueva")
        cached_data = {
            'rsi_data': [],
            'last_update': datetime.utcnow().isoformat()
        }

# Guardar datos en caché
def save_cache():
    with data_lock:
        data_to_cache = {
            'rsi_data': rsi_data.to_dict(orient='records'),
            'last_update': last_update_time.isoformat()
        }
    
    with open('data_cache.json', 'w') as f:
        json.dump(data_to_cache, f)
    print("Datos guardados en caché")

# Funciones de cálculo
def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

# Obtener datos históricos desde CoinGecko
def get_historical_data(coin_id, days=30):
    try:
        url = f"{COINGECKO_API}/coins/{coin_id}/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': 'daily'
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        if 'prices' in data and data['prices']:
            df = pd.DataFrame(data['prices'], columns=['ts', 'price'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms')
            df.set_index('ts', inplace=True)
            return df
    except Exception as e:
        print(f"Error obteniendo datos para {coin_id}: {str(e)[:100]}")
    return None

# Obtener volumen de trading
def get_volume(coin_id):
    try:
        url = f"{COINGECKO_API}/coins/{coin_id}"
        response = requests.get(url, timeout=15)
        data = response.json()
        return data['market_data']['total_volume']['usd']
    except:
        return 0

# Calcular RSI para diferentes timeframes
def calculate_timeframe_rsi(df, timeframe, period=14):
    # Simular diferentes timeframes con resampling
    if timeframe == '15m':
        resampled = df['price'].resample('15T').ohlc().dropna()
    elif timeframe == '30m':
        resampled = df['price'].resample('30T').ohlc().dropna()
    elif timeframe == '1h':
        resampled = df['price'].resample('1H').ohlc().dropna()
    elif timeframe == '2h':
        resampled = df['price'].resample('2H').ohlc().dropna()
    elif timeframe == '4h':
        resampled = df['price'].resample('4H').ohlc().dropna()
    elif timeframe == '1d':
        resampled = df['price'].resample('1D').ohlc().dropna()
    elif timeframe == '1w':
        resampled = df['price'].resample('1W').ohlc().dropna()
    else:
        return 50
    
    if resampled.empty:
        return 50
    
    # Calcular RSI para el timeframe
    rsi = compute_rsi(resampled['close'], period)
    return rsi.iloc[-1] if not rsi.empty else 50

def fetch_all_data():
    global rsi_data, last_update_time
    
    print("Iniciando actualización de datos...")
    start_time = time.time()
    rsi_results = []
    volume_results = []
    
    try:
        # Obtener datos para BTC primero
        btc_data = {}
        btc_df = get_historical_data('bitcoin', 30)
        volume = get_volume('bitcoin')
        
        if btc_df is not None:
            for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
                btc_data[tf] = calculate_timeframe_rsi(btc_df, tf, current_config['rsi_period'])
        
        btc_data['symbol'] = 'BTC/USDT'
        btc_data['volume'] = volume
        rsi_results.append(btc_data)
        volume_results.append(volume)
        print(f"Datos de BTC obtenidos")
    except Exception as e:
        print(f"Error procesando BTC: {e}")
    
    # Obtener datos para altcoins
    for coin_id in symbols:
        if coin_id == 'bitcoin':
            continue
            
        try:
            asset_data = {}
            coin_df = get_historical_data(coin_id, 30)
            volume = get_volume(coin_id)
            
            if coin_df is not None:
                for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
                    asset_data[tf] = calculate_timeframe_rsi(coin_df, tf, current_config['rsi_period'])
            
            # Formatear símbolo para mostrar
            symbol_name = coin_id.upper() if coin_id == 'btc' else coin_id.replace('-', ' ').title()
            asset_data['symbol'] = f"{symbol_name}/USDT"
            asset_data['volume'] = volume
            rsi_results.append(asset_data)
            volume_results.append(volume)
            print(f"Datos de {coin_id} obtenidos")
            time.sleep(0.5)  # Respetar rate limit
        except Exception as e:
            print(f"Error procesando {coin_id}: {e}")
    
    if rsi_results:
        df = pd.DataFrame(rsi_results)
        
        # Calcular categorías de volumen
        if volume_results:
            high_thresh = np.percentile(volume_results, 70)
            low_thresh = np.percentile(volume_results, 30)
            df['volume_cat'] = df.apply(lambda row: 
                'Alto' if row['volume'] >= high_thresh else 
                'Bajo' if row['volume'] <= low_thresh else 
                'Medio', axis=1)
        else:
            df['volume_cat'] = ['Medio'] * len(rsi_results)
        
        with data_lock:
            rsi_data = df
            last_update_time = datetime.utcnow()
        
        # Guardar en caché
        save_cache()
    
    elapsed = time.time() - start_time
    print(f"Datos actualizados en {elapsed:.2f} segundos")
    print(f"Criptos obtenidas: {len(rsi_results)}/{len(symbols)}")
    return True

def create_plot():
    global rsi_data
    
    # Intentar cargar datos si están vacíos
    if rsi_data.empty:
        load_cache()
        if cached_data and cached_data['rsi_data']:
            rsi_data = pd.DataFrame(cached_data['rsi_data'])
            last_update_time = datetime.fromisoformat(cached_data['last_update'])
    
    # Crear figura
    fig = go.Figure()
    
    if rsi_data.empty:
        fig.add_annotation(
            text="No se pudieron cargar datos. Intente actualizar más tarde.",
            x=0.5, y=0.5, 
            showarrow=False, 
            font=dict(size=24, color="red")
        )
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            height=700
        )
        return fig
    
    # Filtrar datos
    plot_data = rsi_data.copy()
    if current_config['volume_filter'] != 'Todas':
        plot_data = plot_data[plot_data['volume_cat'] == current_config['volume_filter']]
    
    # Obtener ejes
    x_time, y_time = current_config['timeframe']
    
    # Crear trazas
    traces = []
    for i, row in plot_data.iterrows():
        symbol = row['symbol']
        color = 'gold' if 'BTC' in symbol else \
                'green' if row['volume_cat'] == 'Alto' else \
                'blue' if row['volume_cat'] == 'Medio' else 'red'
        
        size = 50 if 'BTC' in symbol else 30
        name = symbol.split('/')[0]
        
        if 'BTC' in symbol:
            textfont = dict(size=18, color='darkorange', family='Arial', weight='bold')
        else:
            textfont = dict(size=14, color='black', weight='bold')
        
        # Verificar si existen los valores RSI
        if x_time in row and y_time in row and not pd.isna(row[x_time]) and not pd.isna(row[y_time]):
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
    
    # Añadir trazas a la figura
    fig = go.Figure(data=traces)
    
    # Añadir líneas de referencia
    fig.add_shape(type="line", 
                  x0=current_config['lower_x'], y0=0, 
                  x1=current_config['lower_x'], y1=100,
                  line=dict(color="Green", width=3, dash="dash"))
    fig.add_shape(type="line", 
                  x0=current_config['upper_x'], y0=0, 
                  x1=current_config['upper_x'], y1=100,
                  line=dict(color="Red", width=3, dash="dash"))
    fig.add_shape(type="line", 
                  x0=0, y0=current_config['lower_y'], 
                  x1=100, y1=current_config['lower_y'],
                  line=dict(color="Green", width=3, dash="dash"))
    fig.add_shape(type="line", 
                  x0=0, y0=current_config['upper_y'], 
                  x1=100, y1=current_config['upper_y'],
                  line=dict(color="Red", width=3, dash="dash"))
    
    # Añadir zonas
    fig.add_hrect(y0=current_config['upper_y'], y1=100,
                  line_width=0, fillcolor="red", opacity=0.15)
    fig.add_hrect(y0=0, y1=current_config['lower_y'],
                  line_width=0, fillcolor="green", opacity=0.15)
    fig.add_vrect(x0=current_config['upper_x'], x1=100,
                  line_width=0, fillcolor="red", opacity=0.15)
    fig.add_vrect(x0=0, x1=current_config['lower_x'],
                  line_width=0, fillcolor="green", opacity=0.15)
    
    # Configurar layout
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M (UTC)")
    title = f"RSI ({current_config['timeframe'][0]} vs {current_config['timeframe'][1]}) | Período: {current_config['rsi_period']} | Filtro: {current_config['volume_filter']}"
    
    fig.update_layout(
        title=dict(text=f"{title}<br>{now}", font=dict(size=24)),
        xaxis_title=f"RSI {current_config['timeframe'][0]} (Límites: {current_config['lower_x']}/{current_config['upper_x']})",
        yaxis_title=f"RSI {current_config['timeframe'][1]} (Límites: {current_config['lower_y']}/{current_config['upper_y']})",
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
        height=700,
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
        threading.Thread(target=fetch_all_data).start()
    
    # Crear nuevo gráfico
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs=False)
    
    return jsonify({
        'success': True,
        'graph_html': graph_html,
        'last_update': last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    })

# Programar actualizaciones periódicas
scheduler = BackgroundScheduler()
scheduler.add_job(
    fetch_all_data, 
    'interval', 
    hours=1,  # Actualizar cada hora para no saturar CoinGecko
    max_instances=1
)

# Iniciar la aplicación
if __name__ == '__main__':
    # Cargar caché inicial
    load_cache()
    
    # Carga inicial de datos
    fetch_all_data()
    
    # Iniciar scheduler
    scheduler.start()
    
    # Obtener puerto de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
