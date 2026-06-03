import streamlit as st


def apply_theme():
    st.markdown(
        """
        <style>
        :root {
            --brand: #b43d1f;
            --brand-dark: #7f2a19;
            --ink: #18212f;
            --muted: #667085;
            --panel: #fff7f3;
            --line: #ead8cf;
            --surface: #ffffff;
            --page: #f8fafc;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: var(--page);
            color: var(--ink);
        }

        .main .block-container {
            max-width: 1120px;
            padding-top: 1.4rem;
            padding-bottom: 7rem;
        }

        h1, h2, h3, h4, h5, h6,
        p, li, label,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            color: var(--ink);
        }

        [data-testid="stCaptionContainer"], small {
            color: var(--muted);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #fff7f3 0%, #ffffff 76%);
            border-right: 1px solid var(--line);
        }

        [data-testid="stSidebar"] * {
            color: var(--ink);
        }

        .app-hero {
            border: 1px solid var(--line);
            background: linear-gradient(135deg, #fff7f3 0%, #ffffff 62%, #f4fbff 100%);
            border-radius: 14px;
            padding: 1.35rem 1.5rem;
            margin-bottom: 1rem;
        }

        .app-kicker {
            color: var(--brand-dark);
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }

        .app-title {
            color: var(--ink);
            font-size: 2.05rem;
            line-height: 1.1;
            font-weight: 820;
            margin: 0 0 0.45rem 0;
        }

        .app-subtitle {
            color: var(--muted);
            font-size: 1rem;
            max-width: 820px;
            margin: 0;
        }

        .status-card {
            border: 1px solid #e8edf2;
            border-radius: 10px;
            padding: 0.8rem 0.9rem;
            background: var(--surface);
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        .status-label {
            color: var(--muted);
            font-size: 0.78rem;
            margin-bottom: 0.2rem;
        }

        .status-value {
            color: var(--ink);
            font-weight: 720;
            font-size: 0.96rem;
        }

        .maturity-card {
            margin-bottom: 0.65rem;
        }

        .maturity-note {
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.45;
            margin-top: 0.35rem;
        }

        .workflow-strip {
            border: 1px solid #e8edf2;
            border-radius: 12px;
            background: #ffffff;
            padding: 0.95rem;
            margin: 0 0 1.3rem 0;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        .workflow-heading {
            color: var(--ink);
            font-weight: 780;
            font-size: 1rem;
            margin-bottom: 0.75rem;
        }

        .workflow-steps {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.55rem;
        }

        .workflow-step {
            border: 1px solid #e8edf2;
            border-radius: 10px;
            background: #fbfdff;
            padding: 0.75rem;
            min-height: 98px;
        }

        .workflow-number {
            width: 1.55rem;
            height: 1.55rem;
            border-radius: 999px;
            background: var(--brand);
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.82rem;
            font-weight: 760;
            margin-bottom: 0.45rem;
        }

        .workflow-title {
            color: var(--ink);
            font-size: 0.88rem;
            font-weight: 740;
            margin-bottom: 0.2rem;
        }

        .workflow-copy {
            color: var(--muted);
            font-size: 0.78rem;
            line-height: 1.4;
        }

        .official-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.35rem 0 1.2rem 0;
        }

        .official-card {
            border: 1px solid #e8edf2;
            border-radius: 10px;
            background: #ffffff;
            padding: 0.9rem;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        .official-name {
            color: var(--ink);
            font-weight: 760;
            font-size: 0.98rem;
            margin-bottom: 0.3rem;
        }

        .official-purpose,
        .official-when {
            color: #344054;
            font-size: 0.9rem;
            line-height: 1.5;
            margin-bottom: 0.35rem;
        }

        .official-link {
            color: var(--brand-dark) !important;
            font-weight: 700;
            text-decoration: none;
        }

        .official-link:hover {
            text-decoration: underline;
        }

        .source-note {
            border: 1px solid #b9d8cf;
            border-radius: 10px;
            background: #eef6f4;
            color: #1f4f46;
            padding: 0.75rem 0.85rem;
            margin-bottom: 0.8rem;
            font-size: 0.92rem;
            line-height: 1.5;
        }

        .path-line {
            margin: 0.45rem 0;
            color: var(--ink);
            line-height: 1.55;
        }

        .path-chip {
            display: inline-block;
            max-width: min(100%, 820px);
            padding: 0.12rem 0.45rem;
            border: 1px solid #d9e2ec;
            border-radius: 6px;
            background: #f8fafc;
            color: #344054;
            font-family: Consolas, "Courier New", monospace;
            font-size: 0.88rem;
            overflow-wrap: anywhere;
            vertical-align: baseline;
        }

        div[data-testid="stForm"] {
            border: 1px solid #e8edf2;
            border-radius: 12px;
            background: #ffffff;
            padding: 1rem;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] > div,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
            background: #ffffff !important;
            border: 1px solid #d0d5dd !important;
            border-radius: 10px !important;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04) !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] > div:hover,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] > div:hover {
            border-color: #b8c1cc !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within {
            border-color: var(--brand) !important;
            box-shadow: 0 0 0 3px rgba(180, 61, 31, 0.12) !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] *,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] * {
            color: var(--ink) !important;
        }

        [data-testid="stChatMessage"] {
            border: 1px solid #e8edf2;
            border-radius: 12px;
            padding: 0.65rem 0.85rem;
            background: #ffffff;
            color: var(--ink);
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        [data-testid="stChatMessage"] * {
            color: var(--ink);
        }

        [data-testid="stChatInput"] {
            border-top: 1px solid #edf1f5;
            background: var(--page);
            backdrop-filter: blur(8px);
        }

        [data-testid="stBottomBlockContainer"],
        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] div {
            background: var(--page) !important;
        }

        [data-testid="stChatInput"] textarea,
        textarea,
        input {
            color: var(--ink) !important;
            background: #ffffff !important;
        }

        [data-testid="stChatInput"] textarea {
            border: 1px solid #d0d5dd !important;
            border-radius: 12px !important;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05) !important;
            caret-color: var(--brand) !important;
        }

        [data-testid="stChatInput"] textarea::placeholder {
            color: #667085 !important;
            opacity: 1 !important;
        }

        [data-testid="stChatInput"] textarea:focus,
        [data-testid="stChatInput"] textarea:focus-visible {
            border-color: var(--brand) !important;
            outline: 3px solid rgba(180, 61, 31, 0.16) !important;
            box-shadow: 0 0 0 4px rgba(180, 61, 31, 0.10) !important;
        }

        [data-baseweb="select"] input,
        [data-baseweb="select"] input:focus {
            background: transparent !important;
            caret-color: transparent !important;
            color: transparent !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="select"] input,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] input:focus {
            background: transparent !important;
            caret-color: transparent !important;
            color: transparent !important;
            min-width: 1px !important;
            width: 1px !important;
            padding: 0 !important;
            margin: 0 !important;
            border: 0 !important;
            box-shadow: none !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="select"] input::selection {
            background: transparent !important;
            color: transparent !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="tag"] {
            background: #eef6f4 !important;
            border: 1px solid #b9d8cf !important;
            border-radius: 8px !important;
            color: #1f4f46 !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="tag"] span,
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {
            color: #1f4f46 !important;
            fill: #1f4f46 !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="tag"] button,
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] [role="button"] {
            background: transparent !important;
            color: #1f4f46 !important;
        }

        [data-testid="stChatInput"] button {
            background: var(--brand) !important;
            color: #ffffff !important;
            border-color: var(--brand) !important;
            border-radius: 10px !important;
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 8px;
            border: 1px solid var(--line);
            font-weight: 650;
            background: #ffffff;
            color: var(--ink);
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: var(--brand);
            color: var(--brand-dark);
        }

        div[data-testid="stFormSubmitButton"] button,
        div[data-testid="stFormSubmitButton"] button:hover,
        div[data-testid="stFormSubmitButton"] button:focus,
        div[data-testid="stFormSubmitButton"] button:active {
            background: #111827 !important;
            border: 1px solid #111827 !important;
            color: #ffffff !important;
            border-radius: 10px !important;
            font-weight: 750 !important;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08) !important;
        }

        div[data-testid="stFormSubmitButton"] button *,
        div[data-testid="stFormSubmitButton"] button:hover *,
        div[data-testid="stFormSubmitButton"] button:focus * {
            color: #ffffff !important;
            fill: #ffffff !important;
        }

        div[data-testid="stFormSubmitButton"] button:hover {
            background: #374151 !important;
            border-color: #374151 !important;
        }

        button[kind="secondary"] {
            border-radius: 8px !important;
        }

        div[data-testid="stExpander"] {
            border: 1px solid #edf1f5;
            border-radius: 10px;
            background: #fbfcfe;
            color: var(--ink);
        }

        div[data-testid="stExpander"],
        div[data-testid="stExpander"] details,
        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] div {
            background: #ffffff !important;
            color: var(--ink) !important;
        }

        div[data-testid="stExpander"] summary:hover {
            background: #f8fafc !important;
        }

        div[data-testid="stExpander"] *,
        div[data-testid="stExpander"] p,
        div[data-testid="stExpander"] li,
        div[data-testid="stExpander"] span {
            color: var(--ink) !important;
        }

        @media (max-width: 760px) {
            .workflow-steps {
                grid-template-columns: 1fr;
            }
            .official-grid {
                grid-template-columns: 1fr;
            }
            .app-title {
                font-size: 1.55rem;
            }
        }

        /* Mission-control visual refresh */
        :root {
            --brand: #ff6b35;
            --brand-dark: #ff8a4c;
            --accent: #2dd4bf;
            --accent-2: #8bb7ff;
            --ink: #edf7ff;
            --muted: #a9b8c8;
            --panel: #111a24;
            --line: rgba(142, 167, 191, 0.26);
            --surface: #101923;
            --page: #071018;
            --card: #0d1721;
            --card-2: #121f2b;
            --good: #3ddc97;
            --warning: #ffd166;
            --danger: #ff6b6b;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background:
                radial-gradient(circle at 14% 8%, rgba(45, 212, 191, 0.14), transparent 28rem),
                radial-gradient(circle at 82% 0%, rgba(255, 107, 53, 0.13), transparent 26rem),
                linear-gradient(180deg, #071018 0%, #0b121b 46%, #071018 100%) !important;
            color: var(--ink) !important;
        }

        .main .block-container {
            max-width: 1240px;
            padding-top: 1.1rem;
            padding-bottom: 7rem;
        }

        h1, h2, h3, h4, h5, h6,
        p, li, label,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            color: var(--ink) !important;
        }

        h3 {
            margin-top: 1.7rem !important;
            padding-top: 0.1rem;
            font-size: 1.28rem !important;
            letter-spacing: 0 !important;
        }

        h3::before {
            content: "";
            display: inline-block;
            width: 0.55rem;
            height: 0.55rem;
            margin-right: 0.55rem;
            border-radius: 2px;
            background: var(--accent);
            box-shadow: 0 0 18px rgba(45, 212, 191, 0.55);
            vertical-align: 0.08rem;
        }

        [data-testid="stCaptionContainer"], small {
            color: var(--muted) !important;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0a141f 0%, #08111a 100%) !important;
            border-right: 1px solid var(--line) !important;
            box-shadow: 12px 0 34px rgba(0, 0, 0, 0.22);
        }

        [data-testid="stSidebar"] * {
            color: var(--ink) !important;
        }

        [data-testid="stSidebar"] .stCaptionContainer,
        [data-testid="stSidebar"] small,
        [data-testid="stSidebar"] p {
            color: var(--muted) !important;
        }

        .app-hero {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(45, 212, 191, 0.24) !important;
            background:
                linear-gradient(135deg, rgba(15, 27, 39, 0.96) 0%, rgba(10, 21, 31, 0.96) 60%, rgba(39, 24, 18, 0.94) 100%) !important;
            border-radius: 16px !important;
            padding: 1.65rem 1.75rem !important;
            margin-bottom: 1rem !important;
            box-shadow: 0 22px 80px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255,255,255,0.05);
        }

        .app-hero::after {
            content: "";
            position: absolute;
            inset: 0;
            background-image:
                linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
            background-size: 34px 34px;
            mask-image: linear-gradient(90deg, rgba(0,0,0,0.2), rgba(0,0,0,0.9));
            pointer-events: none;
        }

        .app-kicker {
            position: relative;
            z-index: 1;
            color: var(--accent) !important;
            font-size: 0.76rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase;
            margin-bottom: 0.45rem !important;
        }

        .app-title {
            position: relative;
            z-index: 1;
            color: #f8fbff !important;
            font-size: 2.35rem !important;
            line-height: 1.05 !important;
            font-weight: 850 !important;
            margin: 0 0 0.6rem 0 !important;
            text-shadow: 0 0 26px rgba(139, 183, 255, 0.18);
        }

        .app-subtitle {
            position: relative;
            z-index: 1;
            color: #c7d6e6 !important;
            font-size: 1rem !important;
            max-width: 900px;
            margin: 0 !important;
        }

        .hero-signal-row {
            position: relative;
            z-index: 1;
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 1.1rem;
        }

        .hero-signal-row span {
            border: 1px solid rgba(45, 212, 191, 0.26);
            border-radius: 999px;
            background: rgba(45, 212, 191, 0.09);
            color: #dffcf7 !important;
            padding: 0.34rem 0.65rem;
            font-size: 0.78rem;
            font-weight: 700;
        }

        .workflow-strip,
        div[data-testid="stForm"],
        .official-card,
        .status-card,
        [data-testid="stChatMessage"],
        div[data-testid="stExpander"] {
            background: linear-gradient(180deg, rgba(17, 29, 41, 0.96), rgba(12, 22, 32, 0.96)) !important;
            border: 1px solid var(--line) !important;
            border-radius: 14px !important;
            box-shadow: 0 12px 38px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255,255,255,0.04) !important;
            color: var(--ink) !important;
        }

        .workflow-heading,
        .workflow-title,
        .official-name,
        .status-value {
            color: #f7fbff !important;
        }

        .workflow-copy,
        .official-purpose,
        .official-when,
        .status-label {
            color: var(--muted) !important;
        }

        .workflow-step {
            background: rgba(11, 22, 32, 0.82) !important;
            border: 1px solid rgba(139, 183, 255, 0.18) !important;
            border-radius: 12px !important;
        }

        .workflow-number {
            background: linear-gradient(135deg, var(--brand), #ffb15f) !important;
            color: #101923 !important;
            box-shadow: 0 0 18px rgba(255, 107, 53, 0.36);
        }

        .source-note {
            border: 1px solid rgba(45, 212, 191, 0.28) !important;
            border-radius: 12px !important;
            background: rgba(45, 212, 191, 0.08) !important;
            color: #c9f7ef !important;
        }

        .path-chip {
            border: 1px solid rgba(139, 183, 255, 0.24) !important;
            background: rgba(139, 183, 255, 0.08) !important;
            color: #dceaff !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] > div,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] > div,
        input,
        textarea {
            background: rgba(7, 16, 24, 0.82) !important;
            border: 1px solid rgba(139, 183, 255, 0.25) !important;
            color: var(--ink) !important;
            border-radius: 11px !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within,
        input:focus,
        textarea:focus {
            border-color: var(--accent) !important;
            outline: 3px solid rgba(45, 212, 191, 0.15) !important;
            box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.08), 0 0 24px rgba(45, 212, 191, 0.12) !important;
        }

        div[data-testid="stSelectbox"] [data-baseweb="select"] *,
        div[data-testid="stMultiSelect"] [data-baseweb="select"] *,
        [data-baseweb="popover"] * {
            color: var(--ink) !important;
        }

        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {
            background: #0d1721 !important;
            border: 1px solid var(--line) !important;
            color: var(--ink) !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="tag"] {
            background: rgba(255, 107, 53, 0.14) !important;
            border: 1px solid rgba(255, 107, 53, 0.38) !important;
            color: #ffd9c7 !important;
        }

        div[data-testid="stMultiSelect"] [data-baseweb="tag"] span,
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {
            color: #ffd9c7 !important;
            fill: #ffd9c7 !important;
        }

        .stButton > button,
        .stDownloadButton > button {
            background: rgba(15, 28, 40, 0.96) !important;
            border: 1px solid rgba(139, 183, 255, 0.28) !important;
            border-radius: 10px !important;
            color: #edf7ff !important;
            font-weight: 720 !important;
            box-shadow: 0 8px 22px rgba(0, 0, 0, 0.18) !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: var(--accent) !important;
            color: #ffffff !important;
            background: rgba(25, 48, 64, 0.98) !important;
            box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.10), 0 10px 28px rgba(0, 0, 0, 0.25) !important;
        }

        div[data-testid="stFormSubmitButton"] button,
        div[data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stChatInput"] button {
            background: linear-gradient(135deg, var(--brand), #ffb15f) !important;
            border: 1px solid rgba(255, 177, 95, 0.55) !important;
            color: #101923 !important;
            border-radius: 11px !important;
            font-weight: 850 !important;
            box-shadow: 0 0 26px rgba(255, 107, 53, 0.28) !important;
        }

        div[data-testid="stFormSubmitButton"] button *,
        [data-testid="stChatInput"] button * {
            color: #101923 !important;
            fill: #101923 !important;
        }

        [data-testid="stChatInput"],
        [data-testid="stBottomBlockContainer"],
        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] div {
            background: rgba(7, 16, 24, 0.92) !important;
            border-top-color: rgba(139, 183, 255, 0.18) !important;
            backdrop-filter: blur(16px);
        }

        [data-testid="stChatInput"] textarea {
            background: rgba(13, 23, 33, 0.96) !important;
            color: var(--ink) !important;
            border-color: rgba(139, 183, 255, 0.32) !important;
            caret-color: var(--accent) !important;
        }

        [data-testid="stChatInput"] textarea::placeholder,
        textarea::placeholder,
        input::placeholder {
            color: #8ca0b5 !important;
            opacity: 1 !important;
        }

        div[data-testid="stExpander"],
        div[data-testid="stExpander"] details,
        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] div {
            background: rgba(13, 23, 33, 0.96) !important;
            color: var(--ink) !important;
        }

        div[data-testid="stExpander"] summary:hover {
            background: rgba(20, 36, 50, 0.96) !important;
        }

        div[data-testid="stExpander"] *,
        div[data-testid="stExpander"] p,
        div[data-testid="stExpander"] li,
        div[data-testid="stExpander"] span,
        [data-testid="stDataFrame"] *,
        [data-testid="stTable"] * {
            color: var(--ink) !important;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid var(--line) !important;
            border-radius: 12px !important;
            overflow: hidden;
            background: rgba(13, 23, 33, 0.96) !important;
        }

        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.35rem;
            background: rgba(8, 17, 26, 0.9);
            border: 1px solid rgba(139, 183, 255, 0.22);
            border-radius: 14px;
            padding: 0.35rem;
            margin: 0.7rem 0 1.25rem 0;
            box-shadow: 0 12px 34px rgba(0, 0, 0, 0.22);
            position: sticky;
            top: 0.35rem;
            z-index: 10;
            backdrop-filter: blur(16px);
        }

        div[data-testid="stTabs"] button[role="tab"] {
            border-radius: 10px;
            color: var(--muted) !important;
            font-weight: 760;
            padding: 0.55rem 0.8rem;
        }

        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            background: linear-gradient(135deg, rgba(45, 212, 191, 0.18), rgba(139, 183, 255, 0.12));
            color: #ffffff !important;
            border: 1px solid rgba(45, 212, 191, 0.28);
            box-shadow: 0 0 20px rgba(45, 212, 191, 0.14);
        }

        div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
            background-color: transparent !important;
        }

        .stAlert {
            background: rgba(45, 212, 191, 0.08) !important;
            border: 1px solid rgba(45, 212, 191, 0.22) !important;
            color: var(--ink) !important;
        }

        a, .official-link {
            color: #7dd3fc !important;
            text-decoration: none !important;
        }

        a:hover, .official-link:hover {
            color: #bae6fd !important;
            text-decoration: underline !important;
        }

        @media (max-width: 900px) {
            .workflow-steps {
                grid-template-columns: 1fr 1fr !important;
            }
            .app-title {
                font-size: 1.8rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
