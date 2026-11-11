
import streamlit as st


def apply_theme():
    st.markdown(
        """
        <style>

        /* =====================================================
           1. PREMIUM COLOUR PALETTE
        ===================================================== */

        :root {
            --bg: #090E1C;
            --surface: #111A2E;
            --surface2: #172238;
            --surface3: #202B48;

            --white: #FFFFFF;
            --text: #F1F5FF;
            --muted: #B8C5D9;

            --pink: #F472B6;
            --purple: #A78BFA;
            --blue: #60A5FA;
            --cyan: #22D3EE;
            --green: #34D399;
            --yellow: #FBBF24;
            --red: #FB7185;

            --border: rgba(148, 163, 184, 0.20);
            --shadow: 0 5px 18px rgba(0, 0, 0, 0.20);
        }


        /* =====================================================
           2. APPLICATION BACKGROUND
        ===================================================== */

        .stApp {
            background:
                radial-gradient(
                    circle at 5% 5%,
                    rgba(236, 72, 153, 0.10),
                    transparent 28%
                ),
                radial-gradient(
                    circle at 95% 10%,
                    rgba(96, 165, 250, 0.11),
                    transparent 30%
                ),
                radial-gradient(
                    circle at 50% 100%,
                    rgba(52, 211, 153, 0.06),
                    transparent 35%
                ),
                var(--bg) !important;

            color: var(--text) !important;
        }

        [data-testid="stHeader"] {
            background: rgba(9, 14, 28, 0.92) !important;
        }

        [data-testid="stToolbar"] {
            color: white !important;
        }

        .main .block-container {
            max-width: 1500px;
            padding-top: 1.7rem;
            padding-bottom: 3rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }


        /* =====================================================
           3. TYPOGRAPHY
        ===================================================== */

        html,
        body,
        [class*="css"] {
            font-family: "Inter", "Segoe UI", sans-serif;
        }

        h1, h2, h3, h4, h5, h6 {
            color: #FFFFFF !important;
            font-weight: 700 !important;
            letter-spacing: -0.35px !important;
            line-height: 1.35 !important;
        }

        h1 {
            font-size: 2rem !important;

            background: linear-gradient(
                90deg,
                #FFFFFF,
                #F472B6,
                #A78BFA,
                #60A5FA
            );

            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        h2 {
            font-size: 1.55rem !important;
        }

        h3 {
            font-size: 1.2rem !important;
        }

        h4 {
            font-size: 1.05rem !important;
        }

        .stMarkdown,
        [data-testid="stMarkdownContainer"] {
            color: #E8EEFC !important;
            line-height: 1.6;
        }

        .stMarkdown p,
        .stMarkdown li {
            color: #E8EEFC !important;
            line-height: 1.65 !important;
        }

        [data-testid="stCaptionContainer"] {
            color: #B8C5D9 !important;
            font-size: 0.83rem !important;
            line-height: 1.5 !important;
        }

        label {
            color: #E8EEFC !important;
            font-weight: 600 !important;
        }

        
        /* Text fitting and alignment */

        .stMarkdown,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            overflow-wrap: break-word !important;
            word-break: normal !important;
        }

        /* Buttons */

        .stButton > button,
        .stFormSubmitButton > button {
            white-space: normal !important;
            overflow-wrap: break-word !important;
            word-break: normal !important;
            line-height: 1.4 !important;
            text-align: center !important;
        }

        /* Keep card content within its boundaries */

        [data-testid="stMetric"],
        .custom-metric-card,
        .custom-card,
        [data-testid="stVerticalBlockBorderWrapper"] {
            min-width: 0 !important;
        }

        /* Metric text */

        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"] {
            overflow-wrap: break-word !important;
            word-break: normal !important;
        }
        /* =====================================================
           4. SIDEBAR
        ===================================================== */

        [data-testid="stSidebar"] {
            background: linear-gradient(
                180deg,
                #111A2E 0%,
                #1B1A36 55%,
                #102936 100%
            ) !important;

            border-right: 1px solid var(--border);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label {
            color: #FFFFFF !important;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
            color: #E8EEFC !important;
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: #B8C5D9 !important;
        }


        /* =====================================================
           5. BUTTONS - PROFESSIONAL APPEARANCE
        ===================================================== */

        
/* =====================================================
   5. BUTTONS - SOFT PROFESSIONAL APPEARANCE
===================================================== */

        .stButton > button,
        .stFormSubmitButton > button,
        [data-testid="stBaseButton-primary"],
        [data-testid="stBaseButton-secondary"],
        button[kind="primary"],
        button[kind="secondary"] {

            background: linear-gradient(
                115deg,
                #8F285F 0%,
                #633A9B 52%,
                #315B9D 100%
            ) !important;

            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;

            border: 1px solid rgba(167, 139, 250, 0.25) !important;
            border-radius: 10px !important;

            font-weight: 600 !important;
            letter-spacing: 0.1px !important;

            padding: 0.55rem 1rem !important;
            line-height: 1.4 !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;

            opacity: 1 !important;

            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.12) !important;

            transition:
                background 0.18s ease,
                border-color 0.18s ease,
                box-shadow 0.18s ease,
                transform 0.18s ease !important;
        }

        .stButton > button *,
        .stFormSubmitButton > button *,
        [data-testid="stBaseButton-primary"] *,
        [data-testid="stBaseButton-secondary"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            font-weight: 600 !important;
        }

        /* Soft hover effect */

        .stButton > button:hover,
        .stFormSubmitButton > button:hover,
        [data-testid="stBaseButton-primary"]:hover,
        [data-testid="stBaseButton-secondary"]:hover,
        button[kind="primary"]:hover,
        button[kind="secondary"]:hover {

            background: linear-gradient(
                115deg,
                #A33370 0%,
                #7045A8 52%,
                #3968A8 100%
            ) !important;

            border-color: rgba(196, 181, 253, 0.4) !important;

            transform: translateY(-1px) !important;

            box-shadow: 0 2px 7px rgba(0, 0, 0, 0.16) !important;

            filter: none !important;
        }

        /* Keyboard focus */

        .stButton > button:focus-visible,
        .stFormSubmitButton > button:focus-visible {
            outline: 2px solid var(--cyan) !important;
            outline-offset: 3px !important;
        }

        /* Disabled buttons */

        .stButton > button:disabled {
            opacity: 0.5 !important;
            filter: grayscale(0.3);
            cursor: not-allowed !important;
        }



        /* =====================================================
           6. SIDEBAR BUTTONS
        ===================================================== */
        
/* =====================================================
   6. SIDEBAR BUTTONS - SOFT APPEARANCE
===================================================== */

        [data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(
                110deg,
                #76264F,
                #56328A,
                #294D83
            ) !important;

            color: #FFFFFF !important;
            border: 1px solid rgba(167, 139, 250, 0.22) !important;

            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.12) !important;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background: linear-gradient(
                110deg,
                #8B3060,
                #65409A,
                #345B94
            ) !important;

            transform: translateY(-1px) !important;

            box-shadow: 0 2px 7px rgba(0, 0, 0, 0.16) !important;
            filter: none !important;
        }


        /* =====================================================
           7. PAGE NAVIGATION
        ===================================================== */

        [data-testid="stPageLink"] a,
        [data-testid="stSidebarNav"] a {
            color: #E8EEFC !important;
            font-weight: 600 !important;
            border-radius: 9px !important;
            transition: all 0.18s ease !important;
        }

        [data-testid="stPageLink"] a:hover,
        [data-testid="stSidebarNav"] a:hover {
            color: #FFFFFF !important;

            background: rgba(167, 139, 250, 0.13) !important;

            transform: translateX(2px) !important;
        }


        /* =====================================================
           8. TABS
        ===================================================== */

        button[data-baseweb="tab"] {
            color: #DCE5F2 !important;
            font-weight: 650 !important;

            background: rgba(29, 42, 67, 0.55) !important;

            border-radius: 9px 9px 0 0 !important;

            transition: background 0.18s ease !important;
        }

        button[data-baseweb="tab"] p {
            color: inherit !important;
            font-weight: 650 !important;
        }

        button[data-baseweb="tab"]:hover {
            color: #FFFFFF !important;
            background: rgba(167, 139, 250, 0.18) !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: #FFFFFF !important;

            background: rgba(139, 92, 246, 0.19) !important;

            border-bottom: 2px solid #C084FC !important;
        }


        /* =====================================================
           9. FILE UPLOADER
        ===================================================== */

        
/* =====================================================
   9. FILE UPLOADER
===================================================== */

        [data-testid="stFileUploader"] {
            background: rgba(23, 34, 56, 0.72) !important;
            border: 1px dashed rgba(167, 139, 250, 0.40) !important;
            border-radius: 13px !important;
            padding: 13px !important;
            color: #FFFFFF !important;
        }

        [data-testid="stFileUploader"] section {
            background: rgba(29, 42, 67, 0.65) !important;
            border: 1px dashed #64748B !important;
            border-radius: 10px !important;
        }

        [data-testid="stFileUploader"] button {
            background: linear-gradient(
                115deg,
                #8F285F,
                #633A9B,
                #315B9D
            ) !important;

            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;

            border: 1px solid rgba(167, 139, 250, 0.25) !important;
            border-radius: 9px !important;

            font-weight: 600 !important;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.12) !important;

            transition: all 0.18s ease !important;
        }

        [data-testid="stFileUploader"] button:hover {
            background: linear-gradient(
                115deg,
                #A33370,
                #7045A8,
                #3968A8
            ) !important;

            transform: translateY(-1px) !important;
            box-shadow: 0 2px 7px rgba(0, 0, 0, 0.16) !important;
            filter: none !important;
        }

        [data-testid="stFileUploader"] button *,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] small {
            color: #FFFFFF !important;
        }



        /* =====================================================
           10. METRIC CARDS - DASHBOARD
        ===================================================== */

        [data-testid="stMetric"] {
            background: linear-gradient(
                145deg,
                #172238,
                #202B48
            ) !important;

            border: 1px solid rgba(96, 165, 250, 0.23);

            border-radius: 13px;
            padding: 14px 15px !important;

            min-width: 0 !important;
            height: 100%;

            box-shadow: var(--shadow);

            transition:
                border-color 0.2s ease,
                box-shadow 0.2s ease,
                transform 0.2s ease;
        }

        [data-testid="stMetric"]:hover {
            transform: translateY(-2px);

            border-color: rgba(167, 139, 250, 0.65);

            box-shadow:
                0 6px 18px rgba(0, 0, 0, 0.24);
        }

        [data-testid="stMetricLabel"] {
            color: #C2CDE0 !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            line-height: 1.35 !important;
        }

        [data-testid="stMetricLabel"] p {
            color: #C2CDE0 !important;
            font-size: 0.78rem !important;
            overflow-wrap: anywhere !important;
        }

        [data-testid="stMetricValue"] {
            color: #FFFFFF !important;
            font-size: clamp(1.15rem, 1.7vw, 1.65rem) !important;
            font-weight: 750 !important;
            line-height: 1.3 !important;
            overflow-wrap: anywhere !important;
            word-break: break-word !important;
        }

        [data-testid="stMetricDelta"] {
            font-size: 0.78rem !important;
        }


        /* Custom metric cards used by ui.components */

        .custom-metric-card {
            background: linear-gradient(
                145deg,
                #172238,
                #202B48
            );

            border: 1px solid rgba(96, 165, 250, 0.25);
            border-radius: 13px;

            padding: 15px;
            min-width: 0;
            height: 100%;

            box-shadow: var(--shadow);

            overflow: hidden;
            overflow-wrap: anywhere;

            transition:
                border-color 0.2s ease,
                transform 0.2s ease,
                box-shadow 0.2s ease;
        }

        .custom-metric-card:hover {
            transform: translateY(-2px);
            border-color: rgba(167, 139, 250, 0.65);
        }

        .custom-metric-label {
            color: #C2CDE0;
            font-size: 0.78rem;
            font-weight: 600;
            line-height: 1.4;
            overflow-wrap: anywhere;
        }

        .custom-metric-value {
            color: #FFFFFF;
            font-size: clamp(1.2rem, 2vw, 1.65rem);
            font-weight: 750;
            line-height: 1.35;
            margin-top: 7px;
            overflow-wrap: anywhere;
            word-break: break-word;
        }

        .metric-card-help {
            color: #AAB8CE;
            font-size: 0.76rem;
            line-height: 1.45;
            margin-top: 7px;
            overflow-wrap: anywhere;
        }


        /* =====================================================
           11. CONTAINERS AND CUSTOM CARDS
        ===================================================== */

        [data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(17, 26, 46, 0.72) !important;

            border: 1px solid rgba(96, 165, 250, 0.22);
            border-radius: 13px;

            transition:
                border-color 0.2s ease,
                box-shadow 0.2s ease;
        }

        [data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: rgba(167, 139, 250, 0.55);

            box-shadow:
                0 5px 16px rgba(0, 0, 0, 0.18);
        }

        .custom-card {
            background: linear-gradient(
                145deg,
                #172238,
                #202B48
            );

            border: 1px solid rgba(96, 165, 250, 0.25);

            border-radius: 14px;
            padding: 19px;
            margin: 9px 0;

            box-shadow: var(--shadow);

            transition:
                transform 0.2s ease,
                border-color 0.2s ease,
                box-shadow 0.2s ease;
        }

        .custom-card:hover {
            transform: translateY(-2px);
            border-color: rgba(167, 139, 250, 0.65);

            box-shadow:
                0 7px 20px rgba(0, 0, 0, 0.25);
        }


        /* =====================================================
           12. AI HIGHLIGHT PANEL
        ===================================================== */

        .ai-glow {
            background: linear-gradient(
                120deg,
                rgba(236, 72, 153, 0.12),
                rgba(139, 92, 246, 0.14),
                rgba(34, 211, 238, 0.10)
            );

            border: 1px solid rgba(167, 139, 250, 0.35);

            border-radius: 15px;
            padding: 20px;

            box-shadow:
                0 5px 18px rgba(0, 0, 0, 0.18);
        }


        /* =====================================================
           13. INPUT FIELDS
        ===================================================== */

        input,
        textarea {
            background: #172238 !important;
            color: #FFFFFF !important;

            border: 1px solid #475569 !important;
            border-radius: 9px !important;
        }

        input::placeholder,
        textarea::placeholder {
            color: #AAB8CE !important;
            opacity: 1 !important;
        }

        input:focus,
        textarea:focus {
            border-color: #A78BFA !important;
            box-shadow: 0 0 0 1px rgba(167, 139, 250, 0.25) !important;
        }

        [data-baseweb="select"] > div {
            background: #172238 !important;
            color: #FFFFFF !important;
            border-color: #64748B !important;
        }

        [data-baseweb="select"] * {
            color: #FFFFFF !important;
        }

        [data-baseweb="popover"],
        [data-baseweb="menu"] {
            background: #172238 !important;
        }

        [data-baseweb="menu"] * {
            color: #FFFFFF !important;
        }


        /* =====================================================
           14. EXPANDERS
        ===================================================== */

        [data-testid="stExpander"] {
            background: #111A2E !important;

            border: 1px solid rgba(96, 165, 250, 0.25) !important;
            border-radius: 12px !important;
        }

        [data-testid="stExpander"] summary {
            color: #FFFFFF !important;
            font-weight: 650 !important;
        }

        [data-testid="stExpander"] summary:hover {
            color: #D8B4FE !important;
        }


        /* =====================================================
           15. DATA TABLES
        ===================================================== */

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid rgba(96, 165, 250, 0.25);
            border-radius: 11px;
            overflow: hidden;
        }

        [data-testid="stDataFrame"] {
            background: #111A2E !important;
        }


        /* =====================================================
           16. ALERTS
        ===================================================== */

        [data-testid="stAlert"] {
            background: #172238 !important;

            border-radius: 11px !important;
            border: 1px solid rgba(96, 165, 250, 0.3) !important;
        }

        [data-testid="stAlert"] * {
            color: #F1F5FF !important;
        }


        /* =====================================================
           17. CHECKBOXES AND RADIO BUTTONS
        ===================================================== */

        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label {
            color: #FFFFFF !important;
        }


        /* =====================================================
           18. PROGRESS BAR
        ===================================================== */

        [data-testid="stProgress"] > div > div {
            background: linear-gradient(
                90deg,
                #EC4899,
                #8B5CF6,
                #3B82F6,
                #34D399
            ) !important;

            border-radius: 20px;
        }


        /* =====================================================
           19. LINKS
        ===================================================== */

        a {
            color: #60A5FA !important;
            font-weight: 600;
        }

        a:hover {
            color: #F472B6 !important;
        }


        /* =====================================================
           20. CODE BLOCKS
        ===================================================== */

        code,
        pre {
            background: #111A2E !important;
            color: #A5F3FC !important;

            border: 1px solid rgba(96, 165, 250, 0.2);
            border-radius: 8px;
        }


        /* =====================================================
           21. DIVIDERS
        ===================================================== */

        hr {
            border-color: rgba(167, 139, 250, 0.25) !important;
        }


        /* =====================================================
           22. SCROLLBAR
        ===================================================== */

        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: #090E1C;
        }

        ::-webkit-scrollbar-thumb {
            background: #475569;
            border-radius: 10px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #8B5CF6;
        }


        /* =====================================================
           23. PLOTLY CHARTS
        ===================================================== */

        [data-testid="stPlotlyChart"] {
            background: rgba(17, 26, 46, 0.55);
            border: 1px solid rgba(96, 165, 250, 0.18);
            border-radius: 13px;
            padding: 8px;
            min-width: 0;
        }


        
        /* =====================================================
        24. COPILOT - CONSISTENT DARK THEME
        ===================================================== */

        /* Popover and expanded workspace */
        div[data-testid="stPopoverBody"],
        div[data-testid="stDialog"],
        div[data-testid="stDialog"] div[role="dialog"] {
            background: #090E1C !important;
            color: #E8EEFC !important;
        }

        /* Chat cards */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessage"] {
            background: #16213A !important;
            background-color: #16213A !important;
            border: 1px solid #2A3A57 !important;
            border-radius: 14px !important;
            color: #FFFFFF !important;
        }

        /* User message card */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessage"]:has(
            [data-testid="stChatMessageAvatarUser"]
        ) {
            background: #1A2F55 !important;
            border-color: #385987 !important;
        }

        /* Assistant and user message text */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessage"] :is(
            p, span, li, strong, em, h1, h2, h3,
            [data-testid="stMarkdownContainer"]
        ) {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }

        /* Inner message wrappers */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessage"] > div,
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessageContent"],
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stChatMessage"] [data-testid="stVerticalBlock"] {
            background: transparent !important;
        }

        /* Investigation panel and bordered cards */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #111A2E !important;
            border: 1px solid #2A3A57 !important;
            border-radius: 14px !important;
        }

        /* Investigation panel text */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stVerticalBlockBorderWrapper"] :is(
            p, span, label, h1, h2, h3, h4
        ) {
            color: #E8EEFC !important;
            -webkit-text-fill-color: #EBECF0 !important;
        }

        /* Copilot headings and normal text */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stMarkdownContainer"] {
            color: #E8EEFC !important;
        }

        /* Suggested question buttons */
        /* =====================================================
    24. COPILOT - EXPANDED WORKSPACE DARK THEME FIX
    ===================================================== */

    /* Main expanded workspace */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) {
        background: #090E1C !important;
        background-color: #090E1C !important;
        color: #FFFFFF !important;
    }

    /* Workspace inner backgrounds */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) [data-testid="stVerticalBlock"] {
        background-color: transparent !important;
    }

    /* Workspace headings and normal text */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) :is(h1, h2, h3, h4, p, label, span, li, strong) {
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    /* Investigation panel */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) [data-testid="stVerticalBlockBorderWrapper"] {
        background: #111A2E !important;
        background-color: #111A2E !important;
        border: 1px solid #344968 !important;
        border-radius: 14px !important;
    }

    /* All Copilot buttons */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) .stButton > button,
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button[data-testid="stBaseButton-secondary"],
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button[data-testid="stBaseButton-primary"] {

        background: #1A2F55 !important;
        background-color: #1A2F55 !important;

        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;

        border: 1px solid #385987 !important;
        border-radius: 12px !important;
    }

    /* Force button text and nested elements to white */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button *,
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button p,
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button span {

        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    /* Button hover */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) button:hover {
        background: #29466F !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    /* Copilot chat messages */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) [data-testid="stChatMessage"] {
        background: #16213A !important;
        border: 1px solid #344968 !important;
        border-radius: 14px !important;
        color: #FFFFFF !important;
    }

    /* Chat message text */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) [data-testid="stChatMessage"] * {
        color: #FFFFFF !important;
    }

    /* Copilot input fields */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) :is(input, textarea) {
        background: #0F1829 !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        border: 1px solid #344968 !important;
    }

    /* Input placeholder */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) textarea::placeholder {
        color: #AAB8CE !important;
        -webkit-text-fill-color: #AAB8CE !important;
    }

    /* Captions */
    :is(
        [data-testid="stDialog"],
        [data-testid="stPopoverBody"],
        div[role="dialog"],
        div[aria-modal="true"]
    ) [data-testid="stCaptionContainer"] {
        color: #B8C5D9 !important;
    }
        
        /*s(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        button[kind="secondary"] {
            background: #1A2F55 !important;
            color: #FFFFFF !important;
            border: 1px solid #385987 !important;
        }

        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        button[kind="secondary"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }*/

        /* Primary buttons */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        button[kind="primary"] {
            background: linear-gradient(135deg, #4F8DF7, #6D7BF5) !important;
            color: #FFFFFF !important;
        }

        /* Copilot inputs */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        :is(input, textarea, [data-baseweb="input"], [data-baseweb="textarea"]) {
            background: #0F1829 !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            border: 1px solid #344968 !important;
        }

        /* Input placeholder */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        textarea::placeholder {
            color: #9FB0C7 !important;
            -webkit-text-fill-color: #9FB0C7 !important;
        }

        /* Copilot captions */
        :is(div[data-testid="stPopoverBody"], div[data-testid="stDialog"])
        [data-testid="stCaptionContainer"] {
            color: #9FB0C7 !important;
        }



        /* =====================================================
           26. RESPONSIVE LAYOUT
        ===================================================== */

        @media (max-width: 900px) {
            .main .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
            }

            [data-testid="stMetric"] {
                padding: 11px !important;
            }
        }

        @media (max-width: 600px) {
            h1 {
                font-size: 1.55rem !important;
            }

            h2 {
                font-size: 1.3rem !important;
            }

            .main .block-container {
                padding-top: 1rem;
            }
        }


        /* =====================================================
           27. ACCESSIBILITY
        ===================================================== */

        @media (prefers-reduced-motion: reduce) {
            *,
            *::before,
            *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )
