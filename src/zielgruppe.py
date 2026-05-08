# src/zielgruppe.py

# =========================
# GROUND TRUTH: official Bildungsangebot list
# A = Ärzteschaft
# P = Pflege
# S = NDS-Studierende
# PA = Pflegeassistenz
# =========================

 
EVENT_ZIELGRUPPE = {

    # =========================
    # PFLEGE — P only
    # =========================
    "Pflege_Kinaesthetik":  ["P"],      # kinae_bs.py → Kinästhetik Refresher
    "Pflege_Basale":        ["P"],      # kinae_bs.py → Basale Stimulation  
    "Angehoerige":          ["P"],      # angehoerige.py → Kommunikationskurs: schwierige Angehörige
    "Sitzungen_Pflege":     ["P"],      # sitzungen.py → Sitzung Gruppen-, Schicht- und Betriebsleitung

    # =========================
    # PFLEGE — S only
    # =========================
    "NDS_Fallbesprechung":  ["S"],      # nds_fallbesprechung.py → Fallbesprechungen NDS

    # =========================
    # PFLEGE — P / S
    # ========================= 
    "OFOBI":                ["P", "S"], # ofobi.py → OFOBI ICU

    "EPIC_Update":          ["P", "S"],   # EPIC Update Schulungen — Pflege + NDS
    "Fokus_Intensivpflege": ["P", "S"],   # Fokus Intensivpflege — Pflege + NDS
    "Fachentwicklung": ["P", "S"],       #Fachentwicklung
    # =========================
    # PFLEGE — PA only
    # =========================
    "PA_Weiterbildung":     ["PA"],     # pflegeassistenten.py → Fortbildungen für Pflegeassistenz

    # =========================
    # PFLEGE — P / S / (A)
    # =========================
    "Montagscurriculum":    ["P", "S", "A"], # montagscurriculum.py → Montagscurriculum

    # =========================
    # MIXED — A / P
    # =========================
    "KimSim":               ["A", "P"], # kimsim.py → KIM SIM 
    "Mittwoch_Curriculum":  ["A", "P", "S"],      # wednesday.py → Mittwochscurriculum (A primary, P/S optional)
    # =========================
    # ÄRZTESCHAFT — A only
    # =========================

    "Therapieplanung":      ["A"],      # interprof_therapieplanung.py → Interprofessionelle Therapieplanung
    "Teaching_Tuesday":     ["A"],      # teaching_tuesday.py → Teaching Tuesday
    "COD_SENIOR":           ["A"],      # tuesday.py → S-COD (Case of the Day)
    "COD_JUNIOR":           ["A"],      # tuesday.py → COD (Case of the Day)
    "PEER":                 ["A"],      # tuesday.py → Peer-Teaching Session
    "PHYSIO":               ["A"],      # tuesday.py → Physiologie Talk
    "Journal_Club":         ["A"],      # friday.py → Journal Club
    "Bedside_Infektiologie":["A"],      # bedside.py → Bedside Teaching Infektiologie
    "TTE_Curriculum":       ["A"],      # tte.py → TTE Curriculum Lektion 1-10
    "Masterclass":          ["A"],      # masterclass.py → Masterclass
    "Trauma_Board":         ["A"],      # trauma_schockraum.py → med. Schockraumboard / Traumaboard
    "IMC_Updates":          ["A"],      # imc_updates.py → IMC Updates


    

    
    # =========================
    # DIVERSE — per-row checkboxes
    # (actual Zielgruppe read from sheet columns Für Ärzte/Pflege/Studierende/PA)
    # =========================
    "Diverse_Veranstaltungen": ["A", "P", "S", "PA"],  # fallback if no checkboxes
}
