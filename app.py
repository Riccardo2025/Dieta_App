# -*- coding: utf-8 -*-
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# ==========================================
# CONFIGURAZIONE INIZIALE
# ==========================================
st.set_page_config(page_title="Health Manager AI", layout="wide", page_icon="🥗")

# Recupero API Key
try:
    genai.configure(api_key=st.secrets["general"]["GEMINI_API_KEY"])
except Exception as e:
    st.error("Manca la GEMINI_API_KEY nei secrets o c'è un errore di configurazione.")
    st.stop()

# Connessione al DB (Google Sheets)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore di connessione a Google Sheets. Verifica secrets.toml.")
    st.stop()

# ==========================================
# FUNZIONI DI DATABASE (CRUD)
# ==========================================

def leggi_tab(nome_tab):
    """Legge una specifica scheda del Google Sheet"""
    try:
        # ttl=0 assicura che i dati siano sempre freschi
        return conn.read(worksheet=nome_tab, ttl=0)
    except Exception as e:
        st.error(f"Errore lettura DB ({nome_tab}): {e}")
        return pd.DataFrame()

def scrivi_tab(nome_tab, dataframe):
    """Sovrascrive una scheda con il nuovo dataframe"""
    try:
        conn.update(worksheet=nome_tab, data=dataframe)
        st.cache_data.clear() # Pulisce la cache
    except Exception as e:
        st.error(f"Errore scrittura DB: {e}")

def get_studio_info(username_studio):
    """Recupera logo e stile dello studio"""
    df = leggi_tab("CONFIG_STUDI")
    if df.empty: return None
    
    # Assicuriamoci che le colonne siano stringhe per evitare errori
    df['username'] = df['username'].astype(str)
    
    studio = df[df['username'] == str(username_studio)]
    if not studio.empty:
        return studio.iloc[0]
    return None

# ==========================================
# FUNZIONI AI (GEMINI)
# ==========================================
def genera_piano_nutrizionale(testo_analisi, stile_guida, dati_paziente):
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    Agisci come un nutrizionista esperto.
    
    CONTESTO STUDIO:
    Lo studio segue questo approccio rigoroso: "{stile_guida}".
    
    DATI PAZIENTE:
    {dati_paziente}
    
    ANALISI/REFERTI CARICATI:
    {testo_analisi}
    
    COMPITO:
    Crea una bozza di piano alimentare settimanale (solo Lun-Dom) basato sui dati sopra.
    Non usare formattazione complessa, usa elenchi puntati chiari.
    Focalizzati sulle carenze emerse dalle analisi.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Errore generazione: {e}"

# ==========================================
# GESTIONE SESSIONE E LOGIN
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None 
    st.session_state.user_data = None
    st.session_state.linked_studio = None

def login_page():
    st.title("🔐 Portale Nutrizione & Benessere")
    
    tab1, tab2 = st.tabs(["Accesso Professionisti", "Accesso Clienti"])
    
    # --- LOGIN STUDIO ---
    with tab1:
        with st.form("login_studio"):
            user = st.text_input("Username Studio")
            pwd = st.text_input("Password", type="password")
            btn = st.form_submit_button("Entra come Studio")
            
            if btn:
                df = leggi_tab("CONFIG_STUDI")
                if df.empty:
                    st.error("Database Studi vuoto o non raggiungibile.")
                else:
                    # Pulizia dati
                    df['username'] = df['username'].astype(str).str.strip()
                    df['password'] = df['password'].astype(str).str.strip()
                    
                    check = df[(df['username'] == user) & (df['password'] == pwd)]
                    
                    if not check.empty:
                        dati_utente = check.iloc[0]
                        
                        # --- CONTROLLO 3 GIORNI ---
                        # Gestiamo il caso in cui le colonne non esistano ancora nel foglio
                        try:
                            data_iscrizione_str = str(dati_utente.get('data_iscrizione', ''))
                            pagato = str(dati_utente.get('pagato', 'NO')).upper().strip()
                            
                            # Se la data c'è, controlliamo
                            if len(data_iscrizione_str) >= 10: # es. 2024-01-01
                                data_inizio = datetime.strptime(data_iscrizione_str, "%Y-%m-%d")
                                oggi = datetime.now()
                                giorni_passati = (oggi - data_inizio).days
                                
                                if giorni_passati > 3 and pagato != "SI":
                                    st.error(f"⛔ Periodo di prova scaduto da {giorni_passati - 3} giorni.")
                                    st.warning("Contatta l'amministratore per sbloccare l'account.")
                                    st.stop()
                        except Exception as e:
                            # Se c'è un errore nella data, lasciamo passare ma logghiamo (o ignoriamo)
                            print(f"Warning data iscrizione: {e}")

                        # Login ok
                        st.session_state.logged_in = True
                        st.session_state.role = "studio"
                        st.session_state.user_data = dati_utente
                        st.rerun()
                    else:
                        st.error("Credenziali errate.")

    # --- LOGIN CLIENTE ---
    with tab2:
        with st.form("login_cliente"):
            user_c = st.text_input("Username Cliente")
            pwd_c = st.text_input("Password", type="password")
            btn_c = st.form_submit_button("Entra come Cliente")
            
            if btn_c:
                df = leggi_tab("CLIENTI")
                if df.empty:
                    st.error("Database Clienti vuoto.")
                else:
                    df['username'] = df['username'].astype(str).str.strip()
                    df['password'] = df['password'].astype(str).str.strip()
                    
                    check = df[(df['username'] == user_c) & (df['password'] == pwd_c)]
                    if not check.empty:
                        st.session_state.logged_in = True
                        st.session_state.role = "cliente"
                        st.session_state.user_data = check.iloc[0]
                        st.session_state.linked_studio = get_studio_info(check.iloc[0]['studio_riferimento'])
                        st.rerun()
                    else:
                        st.error("Credenziali errate.")

def logout():
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.user_data = None
    st.rerun()

# ==========================================
# INTERFACCIA STUDIO (ADMIN)
# ==========================================
def dashboard_studio():
    dati = st.session_state.user_data
    
    with st.sidebar:
        logo_url = str(dati.get('logo_url', ''))
        if logo_url and logo_url.lower() != "nan":
            st.image(logo_url, use_container_width=True)
        st.title(f"{dati['nome_studio']}")
        
        # Mostra stato abbonamento
        pagato = str(dati.get('pagato', 'NO')).upper()
        if pagato == "SI":
            st.success("✅ Account Premium Attivo")
        else:
            st.warning("⏳ Modalità Prova")
            
        if st.button("Esci"): logout()

    st.subheader(f"👋 Ciao, {dati['username']}")
    
    tabs = st.tabs(["📝 Genera Dieta", "👥 I Miei Clienti", "⚙️ Impostazioni"])

    # TAB 1: GENERATORE
    with tabs[0]:
        df_clienti = leggi_tab("CLIENTI")
        # Filtra clientela dello studio
        miei_clienti = df_clienti[df_clienti['studio_riferimento'] == dati['username']]
        
        if miei_clienti.empty:
            st.warning("Non hai ancora clienti. Aggiungine uno nel tab 'I Miei Clienti'.")
        else:
            cliente_sel = st.selectbox("Seleziona Paziente:", miei_clienti['username'].tolist())
            
            paziente_row = miei_clienti[miei_clienti['username'] == cliente_sel].iloc[0]
            dati_fisici_paziente = paziente_row['dati_fisici']
            
            st.info(f"Dati Paziente: {dati_fisici_paziente}")
            
            uploaded_file = st.file_uploader("Carica Analisi (PDF o Immagine)", type=['pdf', 'png', 'jpg'])
            testo_estratto = ""
            
            if uploaded_file and st.button("🚀 Genera Bozza con AI"):
                with st.spinner("L'IA sta elaborando..."):
                    # Simulazione OCR (qui andrebbe il tuo codice PyPDF2/Image)
                    testo_estratto = f"Analisi caricata: {uploaded_file.name}."
                    
                    bozza = genera_piano_nutrizionale(testo_estratto, dati['stile_guida'], dati_fisici_paziente)
                    st.session_state['bozza_temp'] = bozza 
            
            if 'bozza_temp' in st.session_state:
                st.write("---")
                dieta_finale = st.text_area("Modifica la bozza:", 
                                           value=st.session_state['bozza_temp'], 
                                           height=400)
                
                col1, col2 = st.columns(2)
                with col1:
                    note_interne = st.text_input("Note interne")
                with col2:
                    if st.button("💾 INVIA AL CLIENTE"):
                        df_diete = leggi_tab("DIETE")
                        nuova_riga = pd.DataFrame([{
                            "cliente_username": cliente_sel,
                            "data_assegnazione": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "testo_dieta": dieta_finale,
                            "note_studio": note_interne
                        }])
                        scrivi_tab("DIETE", pd.concat([df_diete, nuova_riga], ignore_index=True))
                        st.success("Inviato!")
                        del st.session_state['bozza_temp']

    # TAB 2: GESTIONE CLIENTI
    with tabs[1]:
        with st.form("new_client"):
            st.write("### Crea Nuovo Paziente")
            nc_user = st.text_input("Username Paziente (univoco)")
            nc_pass = st.text_input("Password Paziente")
            nc_nome = st.text_input("Nome e Cognome")
            nc_dati = st.text_area("Anamnesi / Dati Fisici")
            
            if st.form_submit_button("Crea"):
                df_c = leggi_tab("CLIENTI")
                if nc_user in df_c['username'].values:
                    st.error("Username già in uso.")
                else:
                    new_row = pd.DataFrame([{
                        "username": nc_user,
                        "password": nc_pass,
                        "nome_completo": nc_nome,
                        "studio_riferimento": dati['username'],
                        "dati_fisici": nc_dati
                    }])
                    scrivi_tab("CLIENTI", pd.concat([df_c, new_row], ignore_index=True))
                    st.success("Cliente creato con successo!")
                    time.sleep(1)
                    st.rerun()

    # TAB 3: SETTINGS
    with tabs[2]:
        with st.form("settings"):
            st.write("### Personalizzazione")
            new_logo = st.text_input("URL Logo", value=dati.get('logo_url', ''))
            new_style = st.text_area("Prompt Nutrizionale", value=dati['stile_guida'])
            
            if st.form_submit_button("Salva"):
                df_studi = leggi_tab("CONFIG_STUDI")
                idx = df_studi.index[df_studi['username'] == dati['username']].tolist()[0]
                df_studi.at[idx, 'logo_url'] = new_logo
                df_studi.at[idx, 'stile_guida'] = new_style
                scrivi_tab("CONFIG_STUDI", df_studi)
                
                # Aggiorna sessione
                st.session_state.user_data['logo_url'] = new_logo
                st.session_state.user_data['stile_guida'] = new_style
                st.success("Salvato!")
                st.rerun()

# ==========================================
# INTERFACCIA CLIENTE
# ==========================================
def dashboard_cliente():
    dati = st.session_state.user_data
    studio = st.session_state.linked_studio
    
    with st.sidebar:
        if studio is not None:
            logo = str(studio.get('logo_url', ''))
            if logo and logo.lower() != "nan":
                st.image(logo, use_container_width=True)
            st.caption(f"Studio: {studio['nome_studio']}")
        if st.button("Esci"): logout()

    st.title(f"Ciao, {dati['nome_completo']}")
    
    df_diete = leggi_tab("DIETE")
    my_diets = df_diete[df_diete['cliente_username'] == dati['username']]
    
    if not my_diets.empty:
        ultima = my_diets.iloc[-1]
        st.info(f"📅 Piano del {ultima['data_assegnazione']}")
        with st.container(border=True):
            st.markdown(ultima['testo_dieta'])
    else:
        st.warning("Nessun piano assegnato.")

# ==========================================
# MAIN
# ==========================================
if not st.session_state.logged_in:
    login_page()
else:
    if st.session_state.role == "studio":
        dashboard_studio()
    elif st.session_state.role == "cliente":
        dashboard_cliente()
