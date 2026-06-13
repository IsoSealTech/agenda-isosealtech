import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import random
import smtplib
from email.mime.text import MIMEText
from speech_recognition import Recognizer, AudioFile
import requests
import json
import os
import calendar

# Configuración inicial de la página
st.set_page_config(page_title="Mi Agenda Inteligente", page_icon="📅", layout="centered")

# Forzar la fecha real de Colombia (UTC -5) calculada desde la hora del servidor
ahora_colombia = datetime.utcnow() - timedelta(hours=5)
hoy_colombia = ahora_colombia.date()
ahora_str_comparar = ahora_colombia.strftime("%Y-%m-%d %H:%M:%S")

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

# Funciones de normalización de texto directo (Sin diccionarios intermediarios)
def normalizar_prioridad(x):
    val = str(x).strip().lower()
    if "alt" in val or "urg" in val:
        return "Alta (Urgente)"
    elif "baj" in val or "rut" in val:
        return "Baja (Rutina)"
    return "Media (Importante)"

def normalizar_repeticion(x):
    val = str(x).strip().lower()
    if "dia_s" in val or "seman" in val:
        return "Un día específico (Cada semana)"
    elif "todos" in val or "todos_d" in val:
        return "Todos los días (Semana específica)"
    elif "mes" in val:
        return "Todo un mes específico"
    return "No repetir"

def normalizar_fecha_hora(x):
    val = str(x).strip().replace("/", "-")
    if not val or val == "nan" or val == "None":
        return f"{hoy_colombia} 08:00:00"
    if " " not in val and ":" not in val:
        if len(val) == 10:
            return f"{val} 08:00:00"
        return f"{hoy_colombia} 08:00:00"
    if len(val) > 19:
        val = val[:19]
    return val

# Cargar datos desde Google Sheets a través del puente
def cargar_datos():
    columnas_internas = ["ID", "Tarea", "Fecha_Hora_Entrega", "Prioridad", "Estado", "Repeticion"]
    if API_URL:
        try:
            url_en_vivo = f"{API_URL}?t={int(datetime.now().timestamp())}"
            response = requests.get(url_en_vivo, timeout=10)
            if response.status_code == 200:
                datos_json = response.json()
                if datos_json:
                    df = pd.DataFrame(datos_json)
                    
                    # Normalizar el nombre de la columna física de tu Excel de forma transparente
                    if "Fecha de Entrega" in df.columns:
                        df = df.rename(columns={"Fecha de Entrega": "Fecha_Hora_Entrega"})
                    elif "Fecha_Entrega" in df.columns:
                        df = df.rename(columns={"Fecha_Entrega": "Fecha_Hora_Entrega"})
                    
                    for col in columnas_internas:
                        if col not in df.columns:
                            df[col] = ""
                    
                    df["Estado"] = df["Estado"].fillna("Pendiente").astype(str).str.strip()
                    df["Estado"] = df["Estado"].apply(lambda x: "Pendiente" if x == "" else x)
                    
                    df["Prioridad"] = df["Prioridad"].apply(normalizar_prioridad)
                    df["Repeticion"] = df["Repeticion"].apply(normalizar_repeticion)
                    df["Fecha_Hora_Entrega"] = df["Fecha_Hora_Entrega"].apply(normalizar_fecha_hora)
                    
                    df = df.drop_duplicates(subset=["ID"])
                    return df[columnas_internas]
        except Exception:
            pass
    return pd.DataFrame(columns=columnas_internas)

# Inicializar datos en la sesión de forma limpia
if "df_tareas" not in st.session_state:
    st.session_state.df_tareas = cargar_datos()

st.session_state.df_tareas = st.session_state.df_tareas.drop_duplicates(subset=["ID"])
df_tareas = st.session_state.df_tareas

# Controladores de memoria para el Grabador de Voz
if "texto_grabado" not in st.session_state:
    st.session_state.texto_grabado = ""
if "ultimo_audio_id" not in st.session_state:
    st.session_state.ultimo_audio_id = None

def guardar_datos():
    global df_tareas
    df_tareas = df_tareas.drop_duplicates(subset=["ID"])
    st.session_state.df_tareas = df_tareas
    if API_URL:
        try:
            df_copia = df_tareas.copy()
            # Mapeo exacto hacia la columna real de tu Google Sheets (Fecha de Entrega)
            df_copia = df_copia.rename(columns={"Fecha_Hora_Entrega": "Fecha de Entrega"})
            datos_enviar = df_copia[["ID", "Tarea", "Fecha de Entrega", "Prioridad", "Estado", "Repeticion"]].to_dict(orient="records")
            
            requests.post(API_URL, data=json.dumps(datos_enviar), headers={"Content-Type": "application/json"}, timeout=10)
            st.toast("💾 ¡Agenda sincronizada con Google Sheets!")
        except Exception as e:
            st.toast("⚠️ Guardado localmente en la sesión.")

def calcular_siguiente_fecha_hora(dt_actual, tipo_repeticion):
    if "semana" in tipo_repeticion.lower():
        return dt_actual + timedelta(weeks=1)
    elif "todos" in tipo_repeticion.lower():
        return dt_actual + timedelta(days=1)
    elif "mes" in tipo_repeticion.lower():
        try:
            dias_mes = calendar.monthrange(dt_actual.year, dt_actual.month)[1]
            return dt_actual + timedelta(days=dias_mes)
        except:
            return dt_actual + timedelta(days=30)
    return dt_actual

def enviar_alerta_correo(tareas_urgentes):
    if not CORREO_EMISOR or CORREO_EMISOR == "tu_correo@gmail.com":
        return
    try:
        cuerpo = "Hola, tienes pendientes urgentes para revisar hoy en tu Agenda Inteligente:\n\n"
        for _, row in tareas_urgentes.iterrows():
            prio_panta = row.get('Prioridad', 'Media (Importante)')
            cuerpo += f"• Tarea: {row['Tarea']} | Plazo: {row['Fecha_Hora_Entrega']} | Prioridad: {prio_panta}\n"
        cuerpo += "\n¡Que tengas un excelente y productivo día!"
        
        msg = MIMEText(cuerpo)
        msg['Subject'] = f"⚠️ Recordatorio de Agenda: ¡{len(tareas_urgentes)} pendientes activos!"
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

# Encabezado estructurado
col_titulo, col_logo = st.columns([0.75, 0.25])

with col_titulo:
    st.title("📅 Mi Agenda Inteligente")
    st.write("Guarda tus pendientes por texto o voz de la forma más sencilla.")
    
    if st.button("🔄 Sincronizar / Traer Datos de Google", help="Sincroniza tus dispositivos"):
        st.session_state.df_tareas = cargar_datos()
        st.rerun()

with col_logo:
    if os.path.exists("LOGO ISOSEALTECH.jpg"):
        st.image("LOGO ISOSEALTECH.jpg", use_container_width=True)

# 1. Añadir Nueva Tarea
st.subheader("Añadir Pendiente")

if "audio_key" not in st.session_state:
    st.session_state.audio_key = "grabador_0"

audio_value = st.audio_input("Graba tu tarea o reescríbela encima", key=st.session_state.audio_key)

if audio_value and audio_value != st.session_state.ultimo_audio_id:
    recognizer = Recognizer()
    try:
        with AudioFile(audio_value) as source:
            audio_data = recognizer.record(source)
            texto_transcrito = recognizer.recognize_google(audio_data, language="es-ES")
            st.session_state.texto_grabado = texto_transcrito
            st.session_state.ultimo_audio_id = audio_value
            st.success(f"📝 Transcrito con éxito: \"{texto_transcrito}\"")
    except Exception as e:
        st.error("No se pudo procesar el audio claramente. Intenta grabar de nuevo.")

with st.form("form_tarea", clear_on_submit=True):
    input_tarea = st.text_input("¿Qué debes hacer?", value=st.session_state.texto_grabado)
    
    col_f, col_h = st.columns(2)
    with col_f:
        fecha_entrega = st.date_input("Fecha límite", value=hoy_colombia)
    with col_h:
        hora_entrega = st.time_input("Hora exacta", value=time(8, 0))
        
    prioridad_seleccionada = st.selectbox("Prioridad / Necesidad", ["Alta (Urgente)", "Media (Importante)", "Baja (Rutina)"], index=1)
    repeticion_seleccionada = st.selectbox("¿Se repite esta tarea?", ["No repetir", "Un día específico (Cada semana)", "Todos los días (Semana específica)", "Todo un mes específico"], index=0)
    
    enviar = st.form_submit_button("Guardar en la Agenda")
    
    if enviar and input_tarea:
        nuevo_id = int(datetime.now().strftime("%Y%m%d%H%M%S")) + random.randint(1, 1000)
        dt_combinado = datetime.combine(fecha_entrega, hora_entrega)
        
        nueva_fila = pd.DataFrame([{
            "ID": nuevo_id,
            "Tarea": input_tarea,
            "Fecha_Hora_Entrega": dt_combinado.strftime("%Y-%m-%d %H:%M:%S"),
            "Prioridad": prioridad_seleccionada,
            "Estado": "Pendiente",
            "Repeticion": repeticion_seleccionada
        }])
        st.session_state.df_tareas = pd.concat([st.session_state.df_tareas, nueva_fila], ignore_index=True)
        st.session_state.df_tareas = st.session_state.df_tareas.drop_duplicates(subset=["ID"])
        df_tareas = st.session_state.df_tareas
        guardar_datos()
        
        st.session_state.texto_grabado = ""
        st.session_state.ultimo_audio_id = None
        num_actual = int(st.session_state.audio_key.split("_")[1])
        st.session_state.audio_key = f"grabador_{num_actual + 1}"
        
        st.success("¡Tarea guardada con éxito!")
        st.rerun()

# 2. Recordatorios y Alertas
st.subheader("👀 Alertas y Prioridades")

if not df_tareas.empty:
    tareas_pendientes = df_tareas[df_tareas["Estado"] == "Pendiente"].copy()
else:
    tareas_pendientes = pd.DataFrame()

if not tareas_pendientes.empty:
    urgentes = tareas_pendientes[tareas_pendientes["Fecha_Hora_Entrega"] <= ahora_str_comparar]
    
    if not urgentes.empty:
        st.error(f"⚠️ ¡TIENES {len(urgentes)} TAREAS ACTIVAS O VENCIDAS!")
        for idx, row in urgentes.iterrows():
            rep_text = f" ({row.get('Repeticion', 'No repetir')})" if row.get('Repeticion', 'No repetir') != "No repetir" else ""
            prio_panta = row.get('Prioridad', 'Media (Importante)')
            st.write(f"• **{row['Tarea']}** (Plazo: {row['Fecha_Hora_Entrega']}){rep_text} - *[{prio_panta}]*")
        
        if "alerta_enviada" not in st.session_state:
            enviar_alerta_correo(urgentes)
            st.session_state["alerta_enviada"] = True
            
    st.info("📅 Cuadrícula General de Pendientes Activos:")
    cuadricula_df = tareas_pendientes.copy()
    cuadricula_ordenada = cuadricula_df.sort_values(by="Fecha_Hora_Entrega")
    
    st.dataframe(
        cuadricula_ordenada[["Tarea", "Fecha_Hora_Entrega", "Prioridad", "Repeticion"]].rename(
            columns={
                "Fecha_Hora_Entrega": "Fecha y Hora de Entrega", 
                "Prioridad": "Prioridad", 
                "Repeticion": "Repetición"
            }
        ), 
        use_container_width=True, 
        hide_index=True
    )
else:
    st.success("🎉 ¡Estás al día! No tienes tareas pendientes.")

# 3. Lista General y Gestión de Tareas
st.subheader("🗃️ Todas mis Tareas")

if not df_tareas.empty:
    for idx, row in df_tareas.iterrows():
        col1, col2, col3, col4, col5 = st.columns([0.30, 0.22, 0.18, 0.18, 0.12])
        
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
                try:
                    dt_parsed = datetime.strptime(str(row["Fecha_Hora_Entrega"]), "%Y-%m-%d %H:%M:%S")
                except:
                    dt_parsed = datetime.combine(hoy_colombia, time(8, 0))
                
                nuevo_cambio_dt = st.text_input("Fecha/Hora", value=dt_parsed.strftime("%Y-%m-%d %H:%M"), key=key_fecha, label_visibility="collapsed")
                if nuevo_cambio_dt != dt_parsed.strftime("%Y-%m-%d %H:%M"):
                    try:
                        validar_dt = datetime.strptime(nuevo_cambio_dt, "%Y-%m-%d %H:%M")
                        df_tareas.at[idx, "Fecha_Hora_Entrega"] = validar_dt.strftime("%Y-%m-%d %H:%M:%S")
                        guardar_datos()
                        st.rerun()
                    except:
                        pass
            else:
                st.caption(f"Terminada: {row['Fecha_Hora_Entrega']}")
                
        with col3:
            if row["Estado"] == "Pendiente":
                opciones_rep_panta = ["No repetir", "Un día específico (Cada semana)", "Todos los días (Semana específica)", "Todo un mes específico"]
                val_rep_panta = row.get("Repeticion", "No repetir")
                if val_rep_panta not in opciones_rep_panta:
                    val_rep_panta = "No repetir"
                idx_rep_actual = opciones_rep_panta.index(val_rep_panta)
                
                nueva_rep_cambiada_panta = st.selectbox("Repetición", options=opciones_rep_panta, index=idx_rep_actual, key=key_rep, label_visibility="collapsed")
                if nueva_rep_cambiada_panta != row["Repeticion"]:
                    df_tareas.at[idx, "Repeticion"] = nueva_rep_cambiada_panta
                    guardar_datos()
                    st.rerun()
            else:
                st.caption(f"Repite: {row.get('Repeticion', 'No repetir')}")
                
        with col4:
            if row["Estado"] == "Pendiente":
                opciones_prio_panta = ["Alta (Urgente)", "Media (Importante)", "Baja (Rutina)"]
                val_prio_panta = row.get("Prioridad", "Media (Importante)")
                if val_prio_panta not in opciones_prio_panta:
                    val_prio_panta = "Media (Importante)"
                idx_prio_actual = opciones_prio_panta.index(val_prio_panta)
                
                nueva_prio_cambiada_panta = st.selectbox("Prioridad", options=opciones_prio_panta, index=idx_prio_actual, key=key_prio, label_visibility="collapsed")
                if nueva_prio_cambiada_panta != row["Prioridad"]:
                    df_tareas.at[idx, "Prioridad"] = nueva_prio_cambiada_panta
                    guardar_datos()
                    st.rerun()
            else:
                st.caption(f"Prio: {row.get('Prioridad', 'Media (Importante)')}")
                
        with col5:
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                if row["Estado"] == "Pendiente":
                    if st.button("✔", key=key_completar, help="Completar"):
                        rep_tipo = row.get("Repeticion", "No repetir")
                        if rep_tipo != "No repetir":
                            try:
                                current_dt = datetime.strptime(str(row["Fecha_Hora_Entrega"]), "%Y-%m-%d %H:%M:%S")
                            except:
                                current_dt = datetime.combine(hoy_colombia, time(8, 0))
                            nueva_fecha_hora = calcular_siguiente_fecha_hora(current_dt, rep_tipo)
                            df_tareas.at[idx, "Fecha_Hora_Entrega"] = nueva_fecha_hora.strftime("%Y-%m-%d %H:%M:%S")
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
