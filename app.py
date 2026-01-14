# -*- coding: utf-8 -*-
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import google.generativeai as genai
from datetime import datetime
import time
import gspread
from google.oauth2.service_account import Credentials
import urllib.parse

# ==========================================
# CONFIGURAZIONE PAGINA
# ==========================================
st.set_page_config(page_title="Health Manager AI", layout="wide", page_icon="🥗")

# Recupero API Key Gemini
try:
    genai.configure(api_key=st.secrets["general"]["GEMINI_API_KEY"])
except Exception as e:
    st.error(f"Errore Configurazione Gemini: {e}")
    st.stop()

# Connessione Database (Legge automaticamente da secrets.toml)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore connessione Google Sheets: {e}")
    st.stop()

# ==========================================
# FUNZIONI DATABASE (CRUD)
# ==========================================
def leggi_tab(nome_tab):
    """Legge i dati e li pulisce per evitare errori di login"""
    df = pd.DataFrame()
    
    # 1. TENTATIVO DI LETTURA (Ibrido)
    try:
        # Prova metodo ufficiale
        df = conn.read(worksheet=nome_tab, ttl=0)
    except Exception:
        # Se fallisce, usa metodo CSV (Fallback)
        try:
            url_sheet = st.secrets["connections"]["gsheets"]["spreadsheet"]
            sheet_id = url_sheet.split("/d/")[1].split("/")[0]
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={nome_tab}"
            df = pd.read_csv(csv_url)
        except:
            return pd.DataFrame() # Ritorna vuoto se tutto fallisce

    # 2. PULIZIA DATI (FONDAMENTALE PER IL LOGIN)
    if not df.empty:
        # Pulisce i nomi delle colonne (toglie spazi vuoti errati)
        df.columns = df.columns.str.strip()
        
        # Converte TUTTO il contenuto in testo (così 1234 diventa "1234")
        df = df.astype(str)
        
        # Rimuove spazi vuoti prima e dopo ogni parola in tutte le celle
        for col in df.columns:
            try:
                df[col] = df[col].str.strip()
            except:
                pass

    return df


def scrivi_tab(nome_tab, dataframe):
    """Scrive usando gspread leggendo le credenziali dai Secrets (Cloud Ready)"""
    try:
        # 1. Definisci gli ambiti
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 2. CREAZIONE CREDENZIALI DAI SECRETS (Invece che dal file fisico)
        # Convertiamo l'oggetto secrets in un dizionario python standard
        creds_dict = dict(st.secrets["connections"]["gsheets"])
        
        # Pulizia della chiave privata (spesso i secrets convertono \n in \\n, qui lo correggiamo)
        if "private_key" in creds_dict:
             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 3. Apri il foglio
        url_foglio = st.secrets["connections"]["gsheets"]["spreadsheet"]
        sheet = client.open_by_url(url_foglio).worksheet(nome_tab)
        
        # 4. Prepara l'ultima riga
        ultima_riga = dataframe.iloc[-1].tolist()
        ultima_riga = [str(x) for x in ultima_riga]
        
        # 5. Aggiungi
        sheet.append_row(ultima_riga)
        
        st.cache_data.clear()
        return True
        
    except Exception as e:
        st.error(f"❌ Errore GSPREAD: {e}")
        return False           

# ==========================================
# FUNZIONI AI (GEMINI)
# ==========================================
def genera_piano_nutrizionale(testo_input, stile_studio, obiettivo_cliente, dati_fisici):
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    Agisci come un nutrizionista professionista.
    
    LINEE GUIDA DELLO STUDIO (Brand):
    "{stile_studio}"
    
    PROFILO PAZIENTE:
    - Dati Fisici: {dati_fisici}
    - OBIETTIVO: "{obiettivo_cliente}"
    
    DATI CLINICI / SINTOMI FORNITI:
    "{testo_input}"
    
    COMPITO:
    Crea un piano alimentare settimanale dettagliato.
    1. Rispetta rigorosamente l'obiettivo del paziente.
    2. Adatta lo stile alle linee guida dello studio.
    3. Usa un tono professionale ed empatico.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Errore generazione AI: {e}"

# ==========================================
# GESTIONE LOGIN E STATO
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
                    st.error("Database non raggiungibile o vuoto.")
                else:
                    # --- PULIZIA SPECIALE PER LOGIN ---
                    # 1. Assicuriamoci che i nomi colonne siano minuscoli e senza spazi
                    df.columns = df.columns.str.lower().str.strip()
                    
                    # 2. Convertiamo i dati in stringa
                    df['username'] = df['username'].astype(str).str.strip()
                    df['password'] = df['password'].astype(str).str.strip()
                    
                    # 3. TRUCCO FONDAMENTALE: Rimuovi ".0" se presente alla fine della password
                    # (Questo risolve il problema 1234 diventa 1234.0)
                    df['password'] = df['password'].str.replace(r'\.0$', '', regex=True)

                    # --- DEBUG VISIVO (Così vedi coi tuoi occhi) ---
                    st.write("🔍 Confronto Dati:")
                    st.write(f"Tu hai scritto: '{user}' e '{pwd}'")
                    st.write("Il DB contiene (prime righe):")
                    st.dataframe(df[['username', 'password']].head())
                    # ---------------------------------------------

                    # 4. IL CONTROLLO
                    # Usiamo .str.lower() per ignorare maiuscole/minuscole nello username
                    check = df[
                        (df['username'].str.lower() == user.strip().lower()) & 
                        (df['password'] == pwd.strip())
                    ]
                    
                    if not check.empty:
                        dati_utente = check.iloc[0]
                        
                        # --- CONTROLLO 3 GIORNI (Formato Italiano) ---
                        try:
                            # Cerchiamo la colonna data, gestendo nomi diversi
                            col_data = 'data_iscrizione' if 'data_iscrizione' in df.columns else 'data'
                            col_paga = 'pagato'
                            
                            data_str = str(dati_utente.get(col_data, ''))
                            pagato = str(dati_utente.get(col_paga, 'NO')).upper().strip()
                            
                            if len(data_str) >= 8:
                                try:
                                    d_inizio = datetime.strptime(data_str, "%d/%m/%Y")
                                except:
                                    d_inizio = datetime.strptime(data_str, "%d-%m-%Y")
                                
                                giorni = (datetime.now() - d_inizio).days
                                if giorni > 3 and pagato != "SI":
                                    st.error(f"⛔ Prova scaduta da {giorni-3} giorni.")
                                    st.stop()
                        except Exception as e:
                            print(f"Salto controllo data: {e}")

                        # LOGIN OK
                        st.session_state.logged_in = True
                        st.session_state.role = "studio"
                        st.session_state.user_data = dati_utente
                        st.rerun()
                    else:
                        st.error("❌ Credenziali errate. Controlla la tabella qui sopra.")

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
# DASHBOARD STUDIO
# ==========================================
def dashboard_studio():
    dati = st.session_state.user_data
    
    with st.sidebar:
        logo_url = str(dati.get('logo_url', ''))
        # CORREZIONE WARNING: cambiato use_column_width in use_container_width
        if logo_url and logo_url.lower() != "nan":
            st.image(logo_url, use_container_width=True) 
        
        st.title(f"{dati['nome_studio']}")
        if st.button("Esci"): logout()

    st.subheader(f"Gestione Pazienti - {dati['nome_studio']}")
    
    tabs = st.tabs(["📝 Genera Piano", "👥 Gestione Clienti", "⚙️ Impostazioni"])

    # TAB 1: GENERATORE
    with tabs[0]:
        df_clienti = leggi_tab("CLIENTI")
        miei_clienti = df_clienti[df_clienti['studio_riferimento'] == dati['username']]
        
        if miei_clienti.empty:
            st.warning("Nessun cliente trovato.")
        else:
            col_sel, col_info = st.columns([1, 2], gap="medium")
            
            with col_sel:
                cliente_sel = st.selectbox("👤 Seleziona Paziente:", miei_clienti['username'].tolist())
            
            # Recupera dati aggiornati
            paziente_row = miei_clienti[miei_clienti['username'] == cliente_sel].iloc[0]
            fisico = str(paziente_row.get('dati_fisici', '-'))
            obiettivo = str(paziente_row.get('obiettivo_specifico', 'Standard'))
            
            # Gestione dati mancanti per la visualizzazione
            email_db = str(paziente_row.get('email', ''))
            if email_db == "nan": email_db = ""
            
            tel_db = str(paziente_row.get('telefono', ''))
            if tel_db == "nan": tel_db = ""

            with col_info:
                with st.container(border=True):
                    st.markdown(f"🎯 **Obiettivo:** {obiettivo}")
                    st.caption(f"📏 {fisico} | 📞 {tel_db if tel_db else 'No Tel'} | 📧 {email_db if email_db else 'No Mail'}")

            st.write("---")
            
            # INPUT DATI
            col1, col2 = st.columns(2)
            testo_ai = ""
            
            with col1:
                uploaded_file = st.file_uploader("📂 Carica Referto", type=['pdf', 'png', 'jpg'])
            with col2:
                note_manuali = st.text_area("📝 Note / Sintomi", height=100)

            # PULSANTE GENERA
            if st.button("✨ GENERA PIANO ALIMENTARE ✨", type="primary", use_container_width=True):
                with st.spinner("⏳ Elaborazione intelligenza artificiale..."):
                    if uploaded_file: testo_ai += f" [FILE: {uploaded_file.name}] "
                    if note_manuali: testo_ai += f" {note_manuali} "
                    if not testo_ai: testo_ai = "Nessun dato fornito."

                    bozza = genera_piano_nutrizionale(
                        testo_ai, 
                        dati['stile_guida'], 
                        obiettivo, 
                        fisico
                    )
                    st.session_state['bozza_temp'] = bozza
            
            # SEZIONE REVISIONE E INVIO
            if 'bozza_temp' in st.session_state:
                st.markdown("---")
                dieta_finale = st.text_area("Revisione:", value=st.session_state['bozza_temp'], height=500)
                
                # --- BLOCCO SALVATAGGIO DATABASE ---
                if st.button("💾 SALVA NEL DATABASE (Storico)", use_container_width=True):
                    df_diete = leggi_tab("DIETE")
                    nuova_riga = pd.DataFrame([{
                        "cliente_username": cliente_sel,
                        "data_assegnazione": datetime.now().strftime("%d/%m/%Y"),
                        "testo_dieta": dieta_finale,
                        "note_studio": "Generata via App"
                    }])
                    
                    # Usa concat per preparare il dataframe completo (anche se scrivi_tab usa gspread append)
                    df_completo = pd.concat([df_diete, nuova_riga], ignore_index=True)
                    
                    if scrivi_tab("DIETE", df_completo):
                        st.balloons()
                        st.success("✅ Salvato nello storico del cliente!")

                st.markdown("---")
                st.subheader("📤 Invia al Paziente (o a te stesso)")
                
                # --- BLOCCO INVIO CON CAMPI EDITABILI ---
                c_edit, c_send = st.columns([1, 1], gap="large")
                
                with c_edit:
                    st.caption("Modifica qui sotto per inviare a un numero/email diverso")
                    # Campi modificabili (precompilati con dati DB)
                    dest_tel = st.text_input("📱 Telefono (con prefisso 39...)", value=tel_db)
                    dest_email = st.text_input("📧 Email", value=email_db)
                    
                    # Pulsante per salvare i nuovi contatti nel DB per il futuro
                    if (dest_tel != tel_db or dest_email != email_db) and st.button("🔄 Aggiorna Rubrica Clienti"):
                        # Logica di aggiornamento (Un po' complessa, ricarichiamo tutto il foglio Clienti)
                        df_c = leggi_tab("CLIENTI")
                        # Trova l'indice della riga
                        idx = df_c.index[df_c['username'] == cliente_sel].tolist()[0]
                        # Aggiorna
                        df_c.at[idx, 'telefono'] = dest_tel
                        df_c.at[idx, 'email'] = dest_email
                        # Salva (sovrascrive scheda Clienti)
                        # Nota: Qui usiamo conn.update perché stiamo modificando una riga esistente
                        try:
                            conn.update(worksheet="CLIENTI", data=df_c)
                            st.cache_data.clear()
                            st.success("Rubrica aggiornata!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Errore aggiornamento rubrica: {e}")

                with c_send:
                    st.caption("Clicca per aprire l'app corrispondente")
                    testo_encoded = urllib.parse.quote(f"Ciao {cliente_sel}, ecco il tuo piano nutrizionale:\n\n{dieta_finale}")
                    
                    # WhatsApp Logic
                    if dest_tel:
                        # Rimuovi spazi e + se presenti
                        clean_tel = dest_tel.replace("+", "").replace(" ", "")
                        link_wa = f"https://wa.me/{clean_tel}?text={testo_encoded}"
                        st.link_button("🟢 Invia su WhatsApp", link_wa, use_container_width=True)
                    else:
                        st.button("No Telefono inserito", disabled=True, use_container_width=True)

                    # Email Logic
                    if dest_email and "@" in dest_email:
                        link_mail = f"mailto:{dest_email}?subject=Il tuo Piano Nutrizionale&body={testo_encoded}"
                        st.link_button("📧 Invia per Email", link_mail, use_container_width=True)
                    else:
                        st.button("No Email inserita", disabled=True, use_container_width=True)

    # TAB 2: GESTIONE CLIENTI (Visualizzazione + Creazione)
    with tabs[1]:
        st.subheader("👥 I Tuoi Pazienti")
        
        # 1. VISUALIZZAZIONE LISTA
        df_c = leggi_tab("CLIENTI")
        # Filtra solo i clienti di questo studio
        miei_pazienti = df_c[df_c['studio_riferimento'] == dati['username']]
        
        if not miei_pazienti.empty:
            # Selezioniamo solo le colonne utili da mostrare (nascondiamo password e studio)
            colonne_visibili = ['username', 'nome_completo', 'email', 'telefono', 'dati_fisici', 'obiettivo_specifico']
            # Filtriamo per essere sicuri che le colonne esistano (in caso di vecchie versioni del foglio)
            cols_reali = [c for c in colonne_visibili if c in miei_pazienti.columns]
            
            # Mostra la tabella
            st.dataframe(
                miei_pazienti[cols_reali], 
                use_container_width=True, 
                hide_index=True
            )
            st.caption(f"Totale pazienti: {len(miei_pazienti)}")
        else:
            st.info("Non hai ancora inserito nessun paziente.")

        st.write("---")

        # 2. CREAZIONE NUOVO (Dentro un expander per pulizia)
        with st.expander("➕ AGGIUNGI NUOVO PAZIENTE", expanded=False):
            with st.form("new_client"):
                c1, c2 = st.columns(2)
                with c1:
                    nc_user = st.text_input("Username (univoco per login)")
                    nc_pass = st.text_input("Password (per il paziente)")
                    nc_nome = st.text_input("Nome e Cognome")
                with c2:
                    nc_email = st.text_input("Email")
                    nc_tel = st.text_input("Telefono (es. 39333...)")
                    nc_dati = st.text_input("Dati Fisici (es. 80kg, 180cm)")
                
                nc_obiett = st.text_input("Obiettivo Specifico")
                
                if st.form_submit_button("Salva Nuovo Paziente"):
                    # Rileggiamo il DF per essere sicuri di avere l'ultima versione
                    df_c_fresh = leggi_tab("CLIENTI")
                    
                    if nc_user in df_c_fresh['username'].values:
                        st.error("⚠️ Username già esistente! Scegline un altro.")
                    else:
                        new_row = pd.DataFrame([{
                            "username": nc_user,
                            "password": nc_pass,
                            "nome_completo": nc_nome,
                            "studio_riferimento": dati['username'],
                            "dati_fisici": nc_dati,
                            "obiettivo_specifico": nc_obiett,
                            "email": nc_email,
                            "telefono": nc_tel
                        }])
                        
                        # Usiamo concat + scrivi_tab
                        df_updated = pd.concat([df_c_fresh, new_row], ignore_index=True)
                        
                        if scrivi_tab("CLIENTI", df_updated):
                            st.success(f"✅ Paziente {nc_nome} creato con successo!")
                            time.sleep(1)
                            st.rerun() # Ricarica la pagina per vederlo subito in tabella

# TAB 3: SETTINGS (Impostazioni Studio)
    with tabs[2]:
        st.header("⚙️ Personalizza il tuo Studio")
        st.write("Qui puoi modificare il logo che vedono i clienti e istruire l'IA sul tuo metodo di lavoro.")

        with st.form("settings_form"):
            # Recuperiamo i valori attuali gestendo eventuali "nan" (vuoti)
            current_logo = str(dati.get('logo_url', ''))
            if current_logo == "nan": current_logo = ""

            current_style = str(dati.get('stile_guida', ''))
            if current_style == "nan": current_style = ""

            # Campi di input
            new_logo = st.text_input("URL Logo (Link immagine)", value=current_logo)
            st.caption("Incolla un link diretto a un'immagine (es. da imgur o dal tuo sito web).")

            new_style = st.text_area("Stile Guida Nutrizionale (Prompt IA)", value=current_style, height=200)
            st.caption("Istruisci l'IA: es. 'Prediligi dieta mediterranea', 'Usa tono severo', 'Escludi integratori'.")
            
            # Pulsante di salvataggio
            if st.form_submit_button("💾 Aggiorna Impostazioni"):
                try:
                    # 1. Leggiamo tutto il foglio CONFIG_STUDI
                    df_studi = leggi_tab("CONFIG_STUDI")
                    
                    # 2. Cerchiamo la riga del tuo studio
                    # Puliamo le stringhe per sicurezza
                    df_studi['username'] = df_studi['username'].astype(str).str.strip()
                    target_user = str(dati['username']).strip()
                    
                    if target_user in df_studi['username'].values:
                        # Troviamo l'indice della riga
                        idx = df_studi.index[df_studi['username'] == target_user].tolist()[0]
                        
                        # 3. Aggiorniamo i valori in memoria
                        df_studi.at[idx, 'logo_url'] = new_logo
                        df_studi.at[idx, 'stile_guida'] = new_style
                        
                        # 4. Salvataggio su Google Sheets
                        # NOTA: Qui usiamo conn.update perché stiamo MODIFICANDO, non aggiungendo
                        conn.update(worksheet="CONFIG_STUDI", data=df_studi)
                        st.cache_data.clear()
                        
                        # 5. Aggiorniamo la sessione locale (per vedere le modifiche subito)
                        st.session_state.user_data['logo_url'] = new_logo
                        st.session_state.user_data['stile_guida'] = new_style
                        
                        st.success("✅ Impostazioni aggiornate con successo!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Errore critico: Impossibile trovare il tuo utente nel database per aggiornarlo.")
                        
                except Exception as e:
                    st.error(f"Errore durante il salvataggio: {e}")

# ==========================================
# DASHBOARD CLIENTE
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
        st.warning("Il tuo nutrizionista non ha ancora caricato il piano.")

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

