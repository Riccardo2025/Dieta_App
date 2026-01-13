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
except:
    st.error("Manca la GEMINI_API_KEY nei secrets.")
    st.stop()

# Connessione al DB (Google Sheets)
conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# FUNZIONI DI DATABASE (CRUD)
# ==========================================

def leggi_tab(nome_tab):
    """Legge una specifica scheda del Google Sheet"""
    # ttl=0 assicura che i dati siano sempre freschi e non presi dalla cache
    try:
        return conn.read(worksheet=nome_tab, ttl=0)
    except Exception as e:
        st.error(f"Errore lettura DB ({nome_tab}): {e}")
        return pd.DataFrame()

def scrivi_tab(nome_tab, dataframe):
    """Sovrascrive una scheda con il nuovo dataframe"""
    try:
        conn.update(worksheet=nome_tab, data=dataframe)
        st.cache_data.clear() # Pulisce la cache di Streamlit
    except Exception as e:
        st.error(f"Errore scrittura DB: {e}")

def get_studio_info(username_studio):
    """Recupera logo e stile dello studio"""
    df = leggi_tab("CONFIG_STUDI")
    studio = df[df['username'] == username_studio]
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
    st.session_state.role = None # "studio" o "cliente"
    st.session_state.user_data = None
    st.session_state.linked_studio = None # Per i clienti, sapere chi è il loro nutrizionista

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
    # ... pulizia dati ...
    check = df[(df['username'] == user) & (df['password'] == pwd)]
    
    if not check.empty:
        dati_utente = check.iloc[0]
        
        # --- LOGICA 3 GIORNI ---
        data_iscrizione_str = str(dati_utente['data_iscrizione'])
        pagato = str(dati_utente['pagato']).upper().strip()
        
        try:
            data_inizio = datetime.strptime(data_iscrizione_str, "%Y-%m-%d")
            oggi = datetime.now()
            giorni_passati = (oggi - data_inizio).days
            
            # SE sono passati più di 3 giorni E non ha pagato -> BLOCCA
            if giorni_passati > 3 and pagato != "SI":
                st.error(f"⛔ Periodo di prova scaduto da {giorni_passati - 3} giorni.")
                st.warning("Per continuare a usare il servizio, contatta l'amministratore per il pagamento.")
                st.stop() # Ferma tutto qui
                
        except ValueError:
            # Se la data è scritta male nel foglio, lascialo entrare ma avvisami
            st.warning("Errore data iscrizione. Contattare supporto.")

        # Se tutto ok, procedi col login normale
        st.session_state.logged_in = True

    # --- LOGIN CLIENTE ---
    with tab2:
        with st.form("login_cliente"):
            user_c = st.text_input("Username Cliente")
            pwd_c = st.text_input("Password", type="password")
            btn_c = st.form_submit_button("Entra come Cliente")
            
            if btn_c:
                df = leggi_tab("CLIENTI")
                # Pulizia dati
                df['username'] = df['username'].astype(str).str.strip()
                df['password'] = df['password'].astype(str).str.strip()
                
                check = df[(df['username'] == user_c) & (df['password'] == pwd_c)]
                if not check.empty:
                    st.session_state.logged_in = True
                    st.session_state.role = "cliente"
                    st.session_state.user_data = check.iloc[0]
                    # Recupera info dello studio collegato per mostrare il logo
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
    
    # Sidebar
    with st.sidebar:
        if dati['logo_url'] and str(dati['logo_url']) != "nan":
            st.image(dati['logo_url'], use_container_width=True)
        st.title(f"Studio: {dati['nome_studio']}")
        st.info(f"Stile AI: {dati['stile_guida']}")
        if st.button("Esci"): logout()

    st.subheader(f"👋 Ciao, {dati['username']}")
    
    tabs = st.tabs(["📝 Genera Dieta", "👥 I Miei Clienti", "⚙️ Impostazioni Studio"])

    # TAB 1: GENERATORE
    with tabs[0]:
        st.write("### Crea nuovo piano")
        
        # 1. Seleziona Cliente
        df_clienti = leggi_tab("CLIENTI")
        # Filtra solo i clienti di questo studio
        miei_clienti = df_clienti[df_clienti['studio_riferimento'] == dati['username']]
        
        if miei_clienti.empty:
            st.warning("Non hai ancora clienti. Vai nel tab 'I Miei Clienti' per aggiungerne uno.")
        else:
            cliente_sel = st.selectbox("Seleziona Paziente:", miei_clienti['username'].tolist())
            
            # Recupera dati fisici del cliente selezionato
            dati_fisici_paziente = miei_clienti[miei_clienti['username'] == cliente_sel].iloc[0]['dati_fisici']
            
            # 2. Upload Referti
            uploaded_file = st.file_uploader("Carica Analisi (PDF o Immagine)", type=['pdf', 'png', 'jpg'])
            
            # Variabile per il testo estratto
            testo_estratto = ""
            
            if uploaded_file and st.button("🚀 Genera Bozza con AI"):
                with st.spinner("L'IA sta analizzando i referti e applicando il tuo metodo..."):
                    # Qui (per brevità) assumiamo sia testo semplice o usiamo una simulazione
                    # Nel tuo codice originale avevi già le funzioni PDF/Img, le puoi incollare qui.
                    # Per ora simuliamo che l'IA legga qualcosa:
                    testo_estratto = f"Analisi caricata: {uploaded_file.name}. (Qui ci andrebbe l'OCR vero)"
                    
                    bozza = genera_piano_nutrizionale(testo_estratto, dati['stile_guida'], dati_fisici_paziente)
                    st.session_state['bozza_temp'] = bozza # Salva temporaneamente
            
            # 3. Editor e Salvataggio
            if 'bozza_temp' in st.session_state:
                st.write("---")
                st.write("### ✏️ Modifica e Valida")
                dieta_finale = st.text_area("Correggi la bozza prima di inviarla:", 
                                           value=st.session_state['bozza_temp'], 
                                           height=400)
                
                col1, col2 = st.columns(2)
                with col1:
                    note_interne = st.text_input("Note interne (non visibili al cliente)")
                
                with col2:
                    if st.button("💾 SALVA E INVIA AL CLIENTE"):
                        # Lettura DB Diete
                        df_diete = leggi_tab("DIETE")
                        
                        nuova_riga = pd.DataFrame([{
                            "cliente_username": cliente_sel,
                            "data_assegnazione": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "testo_dieta": dieta_finale,
                            "note_studio": note_interne
                        }])
                        
                        df_aggiornato = pd.concat([df_diete, nuova_riga], ignore_index=True)
                        scrivi_tab("DIETE", df_aggiornato)
                        
                        st.success(f"Dieta inviata correttamente a {cliente_sel}!")
                        del st.session_state['bozza_temp'] # Pulisci

    # TAB 2: GESTIONE CLIENTI
    with tabs[1]:
        st.write("### Aggiungi Nuovo Cliente")
        with st.form("new_client"):
            nc_user = st.text_input("Username (es. m.rossi)")
            nc_pass = st.text_input("Password provvisoria")
            nc_nome = st.text_input("Nome Completo")
            nc_dati = st.text_area("Dati Fisici (Peso, Altezza, Allergie)")
            
            if st.form_submit_button("Crea Cliente"):
                df_c = leggi_tab("CLIENTI")
                if nc_user in df_c['username'].values:
                    st.error("Username già esistente!")
                else:
                    new_row = pd.DataFrame([{
                        "username": nc_user,
                        "password": nc_pass,
                        "nome_completo": nc_nome,
                        "studio_riferimento": dati['username'],
                        "dati_fisici": nc_dati
                    }])
                    scrivi_tab("CLIENTI", pd.concat([df_c, new_row], ignore_index=True))
                    st.success("Cliente creato!")
                    time.sleep(1)
                    st.rerun()

    # TAB 3: IMPOSTAZIONI STUDIO
    with tabs[2]:
        st.write("### Personalizza la tua App")
        st.write("Qui puoi cambiare il logo che vedranno i tuoi clienti e istruire l'IA.")
        
        with st.form("settings_studio"):
            new_logo = st.text_input("URL Logo (es. https://...)", value=dati['logo_url'])
            new_style = st.text_area("Il tuo Stile Nutrizionale (Prompt AI)", value=dati['stile_guida'])
            
            if st.form_submit_button("Aggiorna Impostazioni"):
                df_studi = leggi_tab("CONFIG_STUDI")
                # Trova l'indice della riga dello studio e aggiorna
                idx = df_studi.index[df_studi['username'] == dati['username']].tolist()[0]
                
                df_studi.at[idx, 'logo_url'] = new_logo
                df_studi.at[idx, 'stile_guida'] = new_style
                
                scrivi_tab("CONFIG_STUDI", df_studi)
                
                # Aggiorna anche la sessione locale
                st.session_state.user_data['logo_url'] = new_logo
                st.session_state.user_data['stile_guida'] = new_style
                
                st.success("Impostazioni aggiornate!")
                st.rerun()

# ==========================================
# INTERFACCIA CLIENTE (SOLO VISUALIZZAZIONE)
# ==========================================
def dashboard_cliente():
    dati = st.session_state.user_data
    studio_info = st.session_state.linked_studio
    
    # Sidebar: Mostra il logo dello STUDIO, non dell'app generica!
    with st.sidebar:
        if studio_info is not None and str(studio_info['logo_url']) != "nan":
            st.image(studio_info['logo_url'], use_container_width=True)
            st.caption(f"Seguito da: {studio_info['nome_studio']}")
        else:
            st.header("Il tuo Portale Salute")
            
        if st.button("Esci"): logout()

    st.title(f"Benvenuto, {dati['nome_completo']}")
    
    # Recupera l'ultima dieta
    df_diete = leggi_tab("DIETE")
    # Filtra per questo utente
    le_mie_diete = df_diete[df_diete['cliente_username'] == dati['username']]
    
    if not le_mie_diete.empty:
        # Prende l'ultima in ordine cronologico (assumendo che le nuove siano in fondo)
        ultima = le_mie_diete.iloc[-1]
        
        st.info(f"📅 Piano aggiornato al: {ultima['data_assegnazione']}")
        
        with st.container(border=True):
            st.markdown(ultima['testo_dieta'])
            
        st.caption("Nota: Segui sempre le indicazioni dirette del tuo specialista.")
    else:
        st.warning("Il tuo nutrizionista non ha ancora caricato un piano alimentare per te.")

# ==========================================
# MAIN LOOP
# ==========================================
if not st.session_state.logged_in:
    login_page()
else:
    if st.session_state.role == "studio":
        dashboard_studio()
    elif st.session_state.role == "cliente":

        dashboard_cliente()
