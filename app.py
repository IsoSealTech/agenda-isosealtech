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
    # Vinculación directa con el nombre exacto de tu archivo de imagen
    if os.path.exists("LOGO ISOSEALTECH.jpg"):
        st.image("LOGO ISOSEALTECH.jpg", use_container_width=True)

# 1. Añadir Nueva Tarea
st.subheader("Añadir Pendiente")

audio_value = st.audio_input("Graba tu tarea")
texto_tarea = ""

if audio_value:
    recognizer = Recognizer()
    try:
        with AudioFile(audio_value) as source:
            audio_data = recognizer.record(source)
            texto_tarea = recognizer.recognize_google(audio_data, language="es-ES")
            st.success(f"📝 Transcrito con éxito: \"{texto_tarea}\"")
    except Exception as e:
        st.error("No se pudo procesar el audio claramente.")

with st.form("form_tarea", clear_on_submit=True):
    input_tarea = st.text_input("¿Qué debes hacer?", value=texto_tarea)
    fecha_entrega = st.date_input("Fecha límite / Recordatorio", value=hoy_colombia)
    prioridad = st.selectbox("Prioridad / Necesidad", ["Alta (Urgente)", "Media (Importante)", "Baja (Rutina)"])
    repeticion = st.selectbox("¿Se repite esta tarea?", ["No repetir", "Cada semana", "Cada mes"])
    
    enviar = st.form_submit_button("Guardar en la Agenda")
    
    if enviar and input_tarea:
        nuevo_id = int(datetime.now().strftime("%Y%m%d%H%M%S")) + random.randint(1, 1000)
        nueva_fila = pd.DataFrame([{
            "ID": nuevo_id,
            "Tarea": input_tarea,
            "Fecha de Entrega": fecha_entrega,
            "Prioridad": prioridad,
            "Estado": "Pendiente",
            "Repeticion": repeticion
        }])
        st.session_state.df_tareas = pd.concat([st.session_state.df_tareas, nueva_fila], ignore_index=True)
        df_tareas = st.session_state.df_tareas
        guardar_datos()
        st.success("¡Tarea guardada con éxito!")
        st.rerun()

# 2. Recordatorios y Alertas
st.subheader("👀 Alertas y Prioridades")

hoy = hoy_colombia
if not df_tareas.empty:
    tareas_pendientes = df_tareas[df_tareas["Estado"] == "Pendiente"]
else:
    tareas_pendientes = pd.DataFrame()

if not tareas_pendientes.empty:
    urgentes = tareas_pendientes[tareas_pendientes["Fecha de Entrega"] <= hoy]
    proximas = tareas_pendientes[tareas_pendientes["Fecha de Entrega"] > hoy].sort_values(by="Fecha de Entrega")
    
    if not urgentes.empty:
        st.error(f"⚠️ ¡TIENES {len(urgentes)} TAREAS VENCIDAS O PARA HOY!")
        for idx, row in urgentes.iterrows():
            rep_text = f" ({row['Repeticion']})" if row['Repeticion'] != "No repetir" else ""
            st.write(f"• **{row['Tarea']}** (Vence: {row['Fecha de Entrega']}){rep_text} - *[{row['Prioridad']}]*")
        
        if "alerta_enviada" not in st.session_state:
            enviar_alerta_correo(urgentes)
            st.session_state["alerta_enviada"] = True
            
    if not proximas.empty:
        st.info("📅 Siguientes tareas en el calendario:")
        st.dataframe(proximas[["Tarea", "Fecha de Entrega", "Prioridad", "Repeticion"]], use_container_width=True, hide_index=True)
else:
    st.success("🎉 ¡Estás al día!")

# 3. Lista General y Gestión de Tareas
st.subheader("🗃️ Todas mis Tareas")

if not df_tareas.empty:
    for idx, row in df_tareas.iterrows():
        col1, col2, col3, col4, col5 = st.columns([0.32, 0.18, 0.18, 0.18, 0.14])
        
        key_fecha = f"date_{idx}_{row['ID']}"
        key_rep = f"rep_{idx}_{row['ID']}"
        key_prio = f"prio_{idx}_{row['ID']}"
        key_completar = f"comp_{idx}_{row['ID']}"
        key_eliminar = f"del_{idx}_{row['ID']}"
        
        with col1:
            if row["Estado"] == "Completada":
                st.markdown(f"~~{row['Tarea']}~~")
            else:
                st.markdown(f"**{row['Tarea']}**")
                
        with col2:
            if row["Estado"] == "Pendiente":
                nueva_fecha_cambiada = st.date_input("Fecha", value=row["Fecha de Entrega"], key=key_fecha, label_visibility="collapsed")
                if nueva_fecha_cambiada != row["Fecha de Entrega"]:
                    df_tareas.at[idx, "Fecha de Entrega"] = nueva_fecha_cambiada
                    guardar_datos()
                    st.rerun()
            else:
                st.caption(f"Terminada: {row['Fecha de Entrega']}")
                
        with col3:
            if row["Estado"] == "Pendiente":
                opciones_rep = ["No repetir", "Cada semana", "Cada mes"]
                idx_rep_actual = opciones_rep.index(row["Repeticion"]) if row["Repeticion"] in opciones_rep else 0
                
                nueva_rep_cambiada = st.selectbox("Repetición", options=opciones_rep, index=idx_rep_actual, key=key_rep, label_visibility="collapsed")
                if nueva_rep_cambiada != row["Repeticion"]:
                    df_tareas.at[idx, "Repeticion"] = nueva_rep_cambiada
                    guardar_datos()
                    st.rerun()
            else:
                st.caption(f"Repite: {row['Repeticion']}")
                
        with col4:
            if row["Estado"] == "Pendiente":
                opciones_prio = ["Alta (Urgente)", "Media (Importante)", "Baja (Rutina)"]
                idx_prio_actual = opciones_prio.index(row["Prioridad"]) if row["Prioridad"] in opciones_prio else 1
                
                nueva_prio_cambiada = st.selectbox("Prioridad", options=opciones_prio, index=idx_prio_actual, key=key_prio, label_visibility="collapsed")
                if nueva_prio_cambiada != row["Prioridad"]:
                    df_tareas.at[idx, "Prioridad"] = nueva_prio_cambiada
                    guardar_datos()
                    st.rerun()
            else:
                st.caption(f"Prio: {row['Prioridad']}")
                
        with col5:
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                if row["Estado"] == "Pendiente":
                    if st.button("✔", key=key_completar, help="Completar"):
                        if row["Repeticion"] != "No repetir":
                            nueva_fecha = calcular_siguiente_fecha(row["Fecha de Entrega"], row["Repeticion"])
                            df_tareas.at[idx, "Fecha de Entrega"] = nueva_fecha
                        else:
                            df_tareas.at[idx, "Estado"] = "Completada"
                        guardar_datos()
                        st.rerun()
            with sub_col2:
                if st.button("🗑️", key=key_eliminar, help="Eliminar"):
                    st.session_state.df_tareas = st.session_state.df_tareas.drop(idx).reset_index(drop=True)
                    df_tareas = st.session_state.df_tareas
                    guardar_datos()
                    st.rerun()
else:
    st.caption("La agenda está vacía.")
