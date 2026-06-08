import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import random
import smtplib
from email.mime.text import MIMEText
from speech_recognition import Recognizer, AudioFile
import requests
import json
import os

# Configuración inicial de la página
st.set_page_config(page_title="Mi Agenda Inteligente", page_icon="📅", layout="centered")

# Forzar la fecha real de Colombia (UTC -5) calculada desde la hora del servidor
hoy_colombia = (datetime.utcnow() - timedelta(hours=5)).date()

# CONFIGURACIÓN DEL CORREO DESDE LOS SECRETOS DE LA NUBE
CORREO_EMISOR = st.secrets["CORREO_EMISOR"]
CORREO_RECEPTOR = st.secrets["CORREO_RECEPTOR"]
CONTRASEÑA_CORREO = st.secrets["CONTRASEÑA_CORREO"]

# Obtener la URL del puente de Google Sheets desde Secrets
API_URL = None
try:
    API_URL = st.secrets["connections"]["gsheets"]["spreadsheet"]
except Exception:
    st.error("Por favor, configura la URL de la aplicación web en los Secrets.")

# Cargar datos desde Google Sheets a través del puente
def cargar_datos():
    columnas_limpias = ["ID", "Tarea", "Fecha de Entrega", "Prioridad", "Estado", "Repeticion"]
    if API_URL:
        try:
            response = requests.get(API_URL, timeout=10)
            if response.status_code == 200:
                datos_json = response.json()
                if datos_json:
                    df = pd.DataFrame(datos_json)
                    if "Fecha_Entrega" in df.columns:
                        df = df.rename(columns={"Fecha_Entrega": "Fecha de Entrega"})
                    
                    df["Fecha de Entrega"] = pd.to_datetime(df["Fecha de Entrega"]).dt.date
                    for col in columnas_limpias:
                        if col not in df.columns:
                            if col == "Prioridad":
                                df[col] = "Media (Importante)"
                            elif col == "Repeticion" or col == "Estado":
                                df[col] = "No repetir" if col == "Repeticion" else "Pendiente"
                            else:
                                df[col] = ""
                    return df[columnas_limpias]
        except Exception:
            pass
    return pd.DataFrame(columns=columnas_limpias)

# Inicializar datos en la sesión
if "df_tareas" not in st.session_state:
    st.session_state.df_tareas = cargar_datos()

df_tareas = st.session_state.df_tareas

if "Repeticion" not in df_tareas.columns:
    df_tareas["Repeticion"] = "No repetir"

# --- NUEVO: Controladores de memoria para el Grabador de Voz ---
if "texto_grabado" not in st.session_state:
    st.session_state.texto_grabado = ""
if "ultimo_audio_id" not in st.session_state:
    st.session_state.ultimo_audio_id = None

def guardar_datos():
    st.session_state.df_tareas = df_tareas
    if API_URL:
        try:
            df_copia = df_tareas.copy()
            df_copia["Fecha_Entrega"] = df_copia["Fecha de Entrega"].astype(str)
            datos_enviar = df_copia[["ID", "Tarea", "Fecha_Entrega", "Prioridad", "Estado", "Repeticion"]].to_dict(orient="records")
            
            requests.post(API_URL, data=json.dumps(datos_enviar), headers={"Content-Type": "application/json"}, timeout=10)
            st.toast("💾 ¡Agenda sincronizada con Google Sheets!")
        except Exception as e:
            st.toast("⚠️ Guardado localmente en la sesión.")

def calcular_siguiente_fecha(fecha_actual, tipo_repeticion):
    if tipo_repeticion == "Cada semana":
        return fecha_actual + timedelta(weeks=1)
    elif tipo_repeticion == "Cada mes":
        return fecha_actual + timedelta(days=30)
    return fecha_actual

def enviar_alerta_correo(tareas_urgentes):
    if not CORREO_EMISOR or CORREO_EMISOR == "tu_correo@gmail.com":
        return
    try:
        cuerpo = "Hola, tienes pendientes urgentes para revisar hoy en tu Agenda Inteligente:\n\n"
        for _, row in tareas_urgentes.iterrows():
            cuerpo += f"• Tarea: {row['Tarea']} | Vence: {row['Fecha de Entrega']} | Prioridad: {row['Prioridad']}\n"
        cuerpo += "\n¡Que tengas un excelente y productivo día!"
        
        msg = MIMEText(cuerpo)
        msg['Subject'] = f"⚠️ Recordatorio de Agenda: ¡{len(tareas_urgentes)} pendientes para hoy!"
        msg['From'] = CORREO_EMISOR
        msg['To'] = CORREO_RECEPTOR
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(CORREO_EMISOR, CONTRASEÑA_CORREO)
        server.sendmail(CORREO_EMISOR, CORREO_RECEPTOR, msg.as_string())
        server.quit()
        st.toast("📨 ¡Se te ha enviado un correo de recordatorio!")
    except Exception as e:
        st.sidebar.error(f"No se pudo enviar el correo de alerta: {e}")

# Encabezado con Título a la izquierda y Logo de la Empresa a la derecha
col_titulo, col_logo = st.columns([0.75, 0.25])

with col_titulo:
    st.title("📅 Mi Agenda Inteligente")
    st.write("Guarda tus pendientes por texto o voz de la forma más sencilla.")

with col_logo:
    if os.path.exists("LOGO ISOSEALTECH.jpg"):
        st.image("LOGO ISOSEALTECH.jpg", use_container_width=True)

# 1. Añadir Nueva Tarea
st.subheader("Añadir Pendiente")

# Generamos un ID dinámico para el grabador de audio, permitiendo resetearlo al guardar
if "audio_key" not in st.session_state:
    st.session_state.audio_key = "grabador_0"

audio_value = st.audio_input("Graba tu tarea o reescríbela encima", key=st.session_state.audio_key)

# Procesar el audio solo si es una grabación NUEVA y real
if audio_value and audio_value != st.session_state.ultimo_audio_id:
    recognizer = Recognizer()
    try:
        with AudioFile(audio_value) as source:
            audio_data = recognizer.record(source)
            texto_transcrito = recognizer.
