from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from typing import Callable, Dict, List, Optional
import threading
import time

import pandas as pd
import requests
import yfinance as yf

# ── Stock universes by market code ────────────────────────────────────────────

UNIVERSES: Dict[str, List[str]] = {
    "US": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B", "LLY", "V",
        "JPM", "XOM", "UNH", "MA", "JNJ", "PG", "HD", "MRK", "COST", "ABBV",
        "AVGO", "CVX", "PEP", "KO", "ADBE", "CSCO", "WMT", "CRM", "TMO", "ACN",
        "MCD", "NFLX", "AMD", "ABT", "DHR", "QCOM", "NEE", "TXN", "HON", "PM",
        "LIN", "AMGN", "UPS", "LOW", "SBUX", "INTU", "BA", "CAT", "GS", "MS",
        "BLK", "SPGI", "AXP", "BKNG", "DE", "IBM", "RTX", "MDT", "SYK", "GILD",
        "VRTX", "REGN", "ZTS", "CI", "ELV", "CB", "PYPL", "NOW", "ISRG", "PLD",
        "AMT", "DUK", "SO", "AEP", "F", "GM", "TGT", "TJX", "NKE", "ORCL",
        "T", "VZ", "CMCSA", "DIS", "TMUS", "CVS", "HCA", "UNP", "NSC", "CSX",
        "FDX", "ETN", "EMR", "GE", "MMM", "ADI", "MU", "AMAT", "LRCX", "KLAC",
        "PANW", "CRWD", "SNOW", "DDOG", "NET", "WDAY", "UBER", "ABNB", "PLTR", "COIN",
        "INTC", "WFC", "C", "BAC", "USB", "PNC", "TFC", "COF", "AIG", "MET",
        "OXY", "COP", "EOG", "SLB", "HAL", "DVN", "MPC", "PSX", "VLO", "LNG",
        "MRNA", "PFE", "BMY", "BIIB", "ILMN", "IQV", "MCK", "ABC", "CAH", "HUM",
    ],
    "GB": [
        "HSBA.L", "BP.L", "GSK.L", "SHEL.L", "AZN.L", "RIO.L", "ULVR.L", "DGE.L",
        "LSEG.L", "NG.L", "VOD.L", "BT-A.L", "BA.L", "IMB.L", "BATS.L", "REL.L",
        "EXPN.L", "AUTO.L", "TSCO.L", "MKS.L", "SBRY.L", "NEXT.L", "WPP.L",
        "FLTR.L", "ENT.L", "RMV.L", "MNDI.L", "ABF.L", "KGF.L", "BARC.L",
        "LLOY.L", "NWG.L", "STAN.L", "HLMA.L", "RR.L", "CRH.L", "WEIR.L",
        "FERG.L", "BNZL.L", "DCC.L", "III.L", "PRU.L", "AV.L", "LRE.L",
        "AAL.L", "ANTO.L", "FRES.L", "IMI.L", "PSON.L", "HIK.L", "EZJ.L",
        "IAG.L", "ITV.L", "UU.L", "SVT.L", "PNN.L", "CNA.L", "UTG.L",
        "SGE.L", "DPLM.L", "SMT.L", "PCT.L", "CCH.L", "ADM.L", "MNG.L",
    ],
    "IN_NSE": [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "ITC.NS", "KOTAKBANK.NS", "LT.NS", "SBIN.NS",
        "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS", "BAJFINANCE.NS",
        "WIPRO.NS", "NTPC.NS", "ULTRACEMCO.NS", "POWERGRID.NS", "SUNPHARMA.NS",
        "ONGC.NS", "TITAN.NS", "BAJAJFINSV.NS", "M&M.NS", "TECHM.NS",
        "NESTLEIND.NS", "INDUSINDBK.NS", "ADANIPORTS.NS", "COALINDIA.NS", "TATAMOTORS.NS",
        "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS", "EICHERMOT.NS", "HEROMOTOCO.NS",
        "GRASIM.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "HINDALCO.NS", "BPCL.NS",
        "HDFCLIFE.NS", "SBILIFE.NS", "ICICIGI.NS", "PIDILITIND.NS", "DABUR.NS",
        "MARICO.NS", "BRITANNIA.NS", "COLPAL.NS", "HAVELLS.NS", "TATACONSUM.NS",
        "SHREECEM.NS", "APOLLOHOSP.NS", "MUTHOOTFIN.NS", "BAJAJ-AUTO.NS", "TVSMOTOR.NS",
        "BHARTIARTL.NS", "OBEROIRLTY.NS", "DLF.NS", "GODREJPROP.NS", "ZOMATO.NS",
        "IRCTC.NS", "DMART.NS", "TRENT.NS", "MPHASIS.NS", "PERSISTENT.NS",
        "LTIM.NS", "COFORGE.NS", "OFSS.NS", "KPITTECH.NS", "POLYCAB.NS",
        "CUMMINSIND.NS", "PAGEIND.NS", "WHIRLPOOL.NS", "VOLTAS.NS", "GODREJCP.NS",
    ],
    "IN_BSE": [
        "RELIANCE.BO", "TCS.BO", "HDFCBANK.BO", "INFY.BO", "ICICIBANK.BO",
        "HINDUNILVR.BO", "ITC.BO", "KOTAKBANK.BO", "LT.BO", "SBIN.BO",
        "AXISBANK.BO", "ASIANPAINT.BO", "MARUTI.BO", "HCLTECH.BO", "BAJFINANCE.BO",
        "WIPRO.BO", "NTPC.BO", "ULTRACEMCO.BO", "POWERGRID.BO", "SUNPHARMA.BO",
        "TITAN.BO", "BAJAJFINSV.BO", "M&M.BO", "NESTLEIND.BO", "TATAMOTORS.BO",
        "DRREDDY.BO", "DIVISLAB.BO", "CIPLA.BO", "JSWSTEEL.BO", "TATASTEEL.BO",
    ],
    "DE": [
        "SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "MBG.DE", "BMW.DE", "BAYN.DE",
        "ADS.DE", "BAS.DE", "MUV2.DE", "RWE.DE", "DBK.DE", "CBK.DE", "HEI.DE",
        "VOW3.DE", "MTX.DE", "1COV.DE", "FRE.DE", "MRK.DE", "IFX.DE",
        "EOAN.DE", "DPW.DE", "FME.DE", "DHER.DE", "SHL.DE", "ENR.DE",
        "PAH3.DE", "DB1.DE", "LHA.DE", "AIR.DE", "VNA.DE", "BEI.DE",
        "LEG.DE", "QIA.DE", "ZAL.DE", "HNR1.DE", "PUM.DE", "G1A.DE",
        "TEAM.DE", "BOSS.DE",
    ],
    "FR": [
        "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "BNP.PA", "AI.PA", "RI.PA",
        "CS.PA", "KER.PA", "RMS.PA", "CAP.PA", "DSY.PA", "ATO.PA", "EL.PA",
        "ML.PA", "SGO.PA", "WLN.PA", "PUB.PA", "ACA.PA", "GLE.PA",
        "ENGI.PA", "VIE.PA", "DG.PA", "STLA.PA", "AC.PA", "RNO.PA",
        "VIV.PA", "SU.PA", "ORA.PA", "SW.PA", "ALO.PA", "STM.PA",
        "URW.PA", "LR.PA", "BN.PA", "TEP.PA", "MT.PA", "SK.PA",
        "FP.PA", "EDEN.PA",
    ],
    "JP": [
        "7203.T", "6758.T", "9984.T", "6861.T", "4063.T", "9432.T",
        "7751.T", "6954.T", "9433.T", "4502.T", "8306.T", "8316.T",
        "8411.T", "9022.T", "7267.T", "7269.T", "6501.T", "6503.T",
        "4568.T", "4519.T", "6367.T", "6971.T", "4661.T", "8035.T",
        "9766.T", "6902.T", "7974.T", "6594.T", "4151.T", "9983.T",
    ],
    "HK": [
        "0700.HK", "0941.HK", "1299.HK", "2318.HK", "0005.HK", "0388.HK",
        "1398.HK", "3988.HK", "0939.HK", "2628.HK", "0011.HK", "0012.HK",
        "0016.HK", "0017.HK", "0066.HK", "0175.HK", "0267.HK", "0288.HK",
        "0386.HK", "0669.HK", "0762.HK", "0823.HK", "0857.HK", "0883.HK",
        "0960.HK", "1038.HK", "1044.HK", "1093.HK", "1109.HK", "2020.HK",
    ],
    "AU": [
        "CBA.AX", "BHP.AX", "CSL.AX", "WBC.AX", "NAB.AX", "ANZ.AX",
        "MQG.AX", "RIO.AX", "TLS.AX", "WOW.AX", "WES.AX", "GMG.AX",
        "XRO.AX", "TCL.AX", "ALL.AX", "ASX.AX", "QBE.AX", "IAG.AX",
        "SHL.AX", "COH.AX", "REA.AX", "SEK.AX", "CAR.AX", "APA.AX",
        "ORG.AX", "STO.AX", "FMG.AX", "NST.AX", "EVN.AX", "S32.AX",
        "BSL.AX", "JBH.AX", "HVN.AX", "DXS.AX", "MGR.AX", "AMC.AX",
        "BXB.AX", "TWE.AX", "A2M.AX", "CPU.AX", "MP1.AX", "MIN.AX",
        "NXT.AX", "PMV.AX", "SUL.AX", "ALD.AX", "VUK.AX", "LNK.AX",
        "NHF.AX", "HLS.AX",
    ],
    "CA": [
        "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
        "CNR.TO", "CP.TO", "ENB.TO", "TRP.TO", "SU.TO", "CNQ.TO",
        "IMO.TO", "CVE.TO", "MFC.TO", "SLF.TO", "GWO.TO", "IAG.TO",
        "BAM.TO", "ATD.TO", "L.TO", "WN.TO", "QSR.TO", "MRU.TO",
        "NTR.TO", "TRI.TO", "T.TO", "BCE.TO", "RCI-B.TO", "AEM.TO",
        "ABX.TO", "FNV.TO", "WPM.TO", "AQN.TO", "FTS.TO", "EMA.TO",
        "CU.TO", "DOL.TO", "TFII.TO", "GFL.TO", "WSP.TO", "STN.TO",
        "FFH.TO", "POW.TO", "GWO.TO", "X.TO", "CCO.TO", "BTE.TO",
        "AC.TO", "CAE.TO",
    ],
    "BR": [
        "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "ABEV3.SA",
        "WEGE3.SA", "RENT3.SA", "BPAC11.SA", "RADL3.SA", "LREN3.SA",
        "MGLU3.SA", "NTCO3.SA", "SBSP3.SA", "CMIG4.SA", "ELET3.SA",
        "TAEE11.SA", "EQTL3.SA", "CPFE3.SA", "ENGI11.SA", "EGIE3.SA",
        "SUZB3.SA", "KLBN11.SA", "DXCO3.SA", "HAPV3.SA", "VIVT3.SA",
        "TIMS3.SA", "BBAS3.SA", "SANB11.SA", "ITSA4.SA", "PRIO3.SA",
    ],
    "SG": [
        "D05.SI", "O39.SI", "U11.SI", "Z74.SI", "G13.SI", "C6L.SI",
        "S68.SI", "S63.SI", "BN4.SI", "N2IU.SI", "A17U.SI", "J36.SI",
        "V03.SI", "U96.SI", "H78.SI", "C09.SI", "BS6.SI", "F34.SI",
        "CC3.SI", "9CI.SI", "S58.SI", "ME8U.SI", "M44U.SI", "T82U.SI",
        "BUOU.SI", "K71U.SI", "C52.SI", "U14.SI", "AWX.SI", "42F.SI",
    ],
    "CH": [
        "NESN.SW", "ROG.SW", "NOVN.SW", "AMS.SW", "ZURN.SW", "UHR.SW",
        "ABBN.SW", "CFR.SW", "LONN.SW", "GEBN.SW", "SREN.SW", "SCMN.SW",
        "BALN.SW", "CSGN.SW", "UBSG.SW", "SLHN.SW", "PGHN.SW", "SIKA.SW",
        "GIVN.SW", "HOLN.SW", "LOGN.SW", "TEMN.SW", "LHN.SW", "BARN.SW",
        "VACN.SW", "KARN.SW", "COTN.SW", "BCVN.SW", "LISP.SW", "VBSN.SW",
    ],
    "KR": [
        "005930.KS", "000660.KS", "035420.KS", "051910.KS", "012330.KS",
        "068270.KS", "207940.KS", "006400.KS", "105560.KS", "055550.KS",
        "032830.KS", "086790.KS", "018260.KS", "009150.KS", "000270.KS",
        "251270.KS", "096770.KS", "011200.KS", "034730.KS", "003550.KS",
        "033780.KS", "047050.KS", "003490.KS", "000720.KS", "009830.KS",
        "010130.KS", "006800.KS", "001040.KS", "002790.KS", "004020.KS",
    ],
    "NL": [
        "ASML.AS", "HEIA.AS", "INGA.AS", "PHIA.AS", "WKL.AS", "AD.AS",
        "RAND.AS", "ABN.AS", "AEGON.AS", "NN.AS", "DSM.AS", "AKZA.AS",
        "AGN.AS", "URW.AS", "VPK.AS", "BESI.AS", "SBMO.AS", "TKWY.AS",
        "MT.AS", "FLOW.AS",
    ],
    "ES": [
        "ITX.MC", "SAN.MC", "BBVA.MC", "REP.MC", "TEF.MC", "IBE.MC",
        "NTGY.MC", "ELE.MC", "ACS.MC", "FER.MC", "MAP.MC", "CABK.MC",
        "SAB.MC", "BKT.MC", "UNI.MC", "COL.MC", "MTS.MC", "VIS.MC",
        "ACX.MC", "IAG.MC", "MEL.MC", "AENA.MC", "ENG.MC", "CLNX.MC",
        "GRF.MC", "ALM.MC", "LOG.MC", "TRE.MC", "ROVI.MC", "EDR.MC",
        "IDR.MC", "SGRE.MC", "SLR.MC", "PHP.MC", "OLIN.MC",
    ],
    "SE": [
        # ── Large Cap – Banks & Financials ────────────────────────────────────────
        "NDA-SE.ST", "SEB-A.ST", "SEB-C.ST", "SWED-A.ST", "SHB-A.ST", "SHB-B.ST",
        "INVE-A.ST", "INVE-B.ST", "EQT.ST", "KINV-B.ST", "LUND-B.ST",
        "LATOUR-B.ST", "RATOS-B.ST", "BURE.ST", "INTRUM.ST", "COOR.ST",
        # ── Large Cap – Industrials ───────────────────────────────────────────────
        "VOLV-A.ST", "VOLV-B.ST", "ATCO-A.ST", "ATCO-B.ST", "SAND.ST",
        "ALFA.ST", "SKF-A.ST", "SKF-B.ST", "ASSA-B.ST", "SECU-B.ST", "SKA-B.ST",
        "HEXA-B.ST", "HUSQ-A.ST", "HUSQ-B.ST", "SWECO-B.ST", "ABB.ST",
        "INDT.ST", "SAAB-B.ST", "ADDT-B.ST", "BUFAB.ST", "TROAX.ST",
        "ALIV-SDB.ST", "ELUX-A.ST", "ELUX-B.ST", "DOM.ST", "NOLA-B.ST",
        "LOOMIS.ST", "TREL-B.ST", "ARJO-B.ST", "BRAV.ST", "PEAB-B.ST",
        "EPIROC-A.ST", "EPIROC-B.ST", "LIAB.ST", "SYSR.ST", "BERGB.ST",
        # ── Large Cap – Technology & Telecom ─────────────────────────────────────
        "ERIC-A.ST", "ERIC-B.ST", "TELE2-B.ST", "TELIA.ST", "SINCH.ST", "MYCR.ST",
        # ── Large Cap – Consumer & Retail ─────────────────────────────────────────
        "HM-A.ST", "HM-B.ST", "AXFO.ST", "ICA.ST", "THULE.ST", "MEKO.ST",
        # ── Large Cap – Healthcare & Life Science ─────────────────────────────────
        "ESSITY-A.ST", "ESSITY-B.ST", "GETI-B.ST", "SOBI.ST", "EKTA-B.ST",
        "NIBE-B.ST", "LIFCO-B.ST", "VITRO.ST", "XVIVO.ST", "CAMX.ST",
        "MEDICOVER-B.ST", "RECIP-B.ST",
        # ── Large Cap – Real Estate ───────────────────────────────────────────────
        "BALD-B.ST", "FABG.ST", "JM.ST", "SBB-B.ST", "SAGAX-B.ST",
        "WIHL.ST", "NYFOSA.ST", "DIOS.ST", "HUFV-A.ST", "HUFV-C.ST",
        "PLAZ-B.ST", "CATE.ST", "PNDX-B.ST",
        # ── Large Cap – Materials & Energy ────────────────────────────────────────
        "BOL.ST", "SSAB-A.ST", "SSAB-B.ST", "SCA-A.ST", "SCA-B.ST",
        "HPOL-B.ST", "HOLM-B.ST", "GRNG.ST",
        # ── Large Cap – Gaming, Media & Entertainment ─────────────────────────────
        "EVO.ST", "BETS-B.ST", "KIND-SDB.ST", "EMBRAC-B.ST", "PDX.ST",
        "SF.ST", "NENT-B.ST",
        # ── Mid Cap – Industrials ─────────────────────────────────────────────────
        "ANOD-B.ST", "ADDL-B.ST", "BEIA-B.ST", "BEIJ-B.ST", "BULTEN.ST",
        "ELAN-B.ST", "ELOS-B.ST", "HALD.ST", "HTRO.ST", "IAR-B.ST",
        "INSTAL.ST", "MIDW-B.ST", "NMAN.ST", "PACT.ST", "XANO-B.ST",
        "EOLU-B.ST", "REJL-B.ST", "SEMI.ST", "KLIM-B.ST", "BALCO.ST",
        # ── Mid Cap – Technology ──────────────────────────────────────────────────
        "TRUE-B.ST", "TOBII.ST", "VIT-B.ST", "SECT-B.ST", "ACAST.ST",
        "HEM.ST", "BOOZT.ST", "G5EN.ST", "SPEQTA.ST", "SOF-B.ST",
        # ── Mid Cap – Consumer & Retail ───────────────────────────────────────────
        "CLAS-B.ST", "DUNI.ST", "FOI-B.ST", "NOBI.ST", "SKIS-B.ST",
        "BYGMX.ST", "BYGGMAX.ST",
        # ── Mid Cap – Healthcare & Life Science ───────────────────────────────────
        "CALLIDITAS.ST", "PROBI.ST", "HANSA.ST", "ORX.ST", "OASM.ST",
        "MOB.ST", "IMMU.ST", "ONCO.ST", "FNOX.ST",
        # ── Mid Cap – Real Estate ─────────────────────────────────────────────────
        "CATELLA-B.ST", "SHOT.ST", "NWG.ST", "KFAST-B.ST", "VLTI-B.ST",
        "STORSKOGEN-B.ST", "SFAB.ST",
        # ── Mid Cap – Finance ─────────────────────────────────────────────────────
        "HOFI.ST", "NORX.ST", "CAT-B.ST",
        # ── Mid Cap – Energy & Utilities ──────────────────────────────────────────
        "FENIX-B.ST", "FNM.ST",
        # ── Mid Cap – Media ───────────────────────────────────────────────────────
        "VPLAY-B.ST",
    ],
    "ZA": [
        "NPN.JO", "SOL.JO", "MTN.JO", "BID.JO", "SBK.JO", "FSR.JO",
        "ABG.JO", "NED.JO", "REM.JO", "AGL.JO", "GLN.JO", "IMP.JO",
        "AMS.JO", "SHP.JO", "WHL.JO", "TBS.JO", "BTI.JO", "VOD.JO",
        "TKG.JO", "IPL.JO", "HMN.JO", "LHC.JO", "MOM.JO", "DSY.JO",
        "MMI.JO", "INL.JO", "CPI.JO", "MCG.JO", "MRP.JO", "TFG.JO",
        "SPP.JO", "PIK.JO", "BAW.JO", "PPH.JO", "SSW.JO", "PSG.JO",
        "OCE.JO", "RNI.JO", "FBR.JO", "MNP.JO",
    ],
}

# ── Nordic North universe (Sweden + additional Nordic growth/tech on Nasdaq Stockholm) ─
NORDIC_NORTH: List[str] = list(dict.fromkeys(
    UNIVERSES.get("SE", []) + [
        # ── Additional Nordic-listed growth / tech / healthcare on Nasdaq Stockholm ──
        "CINT.ST", "ENEA.ST", "FORTNOX.ST", "HMS.ST", "KNOW.ST",
        "LIME.ST", "MSAB-B.ST", "NETI-B.ST", "NOTE.ST", "OLINK.ST",
        "OVZON.ST", "QLIRO.ST", "SAAB-B.ST", "SDIPTECH.ST", "SLP-B.ST",
        "VITR.ST", "VIMIAN.ST", "VOLCAR-B.ST", "CIBUS.ST", "CTEK.ST",
        "ELTEL.ST", "HANZA.ST", "IRRAS.ST", "MVIR-B.ST", "NELLY.ST",
        "OEM-B.ST", "PREVAS-B.ST", "RATO-B.ST", "SAGA-B.ST", "SOLT.ST",
        "SVEDBERGS-B.ST", "TAGMASTER.ST", "TELIA.ST", "VICORE.ST",
        "XBRANE.ST", "ADDNODE-B.ST", "ARISE.ST", "BICO.ST",
        "CAM-B.ST", "DORO.ST", "EWORK.ST", "GARO.ST", "IAR-B.ST",
        "IMSOL.ST", "JM.ST", "KDEV.ST", "LATO-B.ST", "MAHA-A.ST",
        "NFO.ST", "NOLA-B.ST", "PREV-B.ST", "QT.ST", "RVRC.ST",
        "SECI.ST", "THULE.ST", "WIHL.ST", "XSPRAY.ST",
    ]
))


# ── Dynamic universe fetching (NASDAQ FTP / Wikipedia / NSE India) ────────────

_UNIVERSE_CACHE: Dict[str, tuple] = {}   # market_code -> (tickers, timestamp)
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 86_400  # 24 hours


def _fetch_us_tickers() -> List[str]:
    """Fetch all NASDAQ and NYSE equity tickers via the NASDAQ screener API.

    Returns stocks with a market cap > 0 (excludes shells and dark instruments
    like rights/units that have no recorded market cap).
    Falls back to Wikipedia S&P 500 + S&P 400 if the API is unreachable.
    """
    hdr = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    tickers: List[str] = []

    for exchange in ("nasdaq", "nyse", "amex"):
        try:
            r = requests.get(
                "https://api.nasdaq.com/api/screener/stocks",
                params={"tableonly": "true", "limit": 10_000, "offset": 0, "exchange": exchange, "download": "true"},
                headers=hdr,
                timeout=30,
            )
            r.raise_for_status()
            rows = r.json().get("data", {}).get("rows") or []
            for row in rows:
                sym = str(row.get("symbol", "")).strip()
                if not sym or not sym[0].isalpha():
                    continue
                # Skip rights, warrants, units which have no recorded market cap
                try:
                    mktcap = float(row.get("marketCap") or 0)
                except (ValueError, TypeError):
                    mktcap = 0
                if mktcap <= 0:
                    continue
                tickers.append(sym)
        except Exception:
            pass

    if tickers:
        return list(dict.fromkeys(tickers))

    # ── Fallback: S&P 500 + S&P 400 from Wikipedia ─────────────────────────────
    try:
        tbls = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", flavor="lxml"
        )
        sp500 = [str(t).replace(".", "-") for t in tbls[0]["Symbol"].tolist()]
        try:
            t400 = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", flavor="lxml"
            )
            col = next(
                c for c in t400[0].columns
                if any(k in str(c).lower() for k in ("ticker", "symbol"))
            )
            sp400 = [str(t).replace(".", "-") for t in t400[0][col].tolist()]
            sp500 = list(dict.fromkeys(sp500 + sp400))
        except Exception:
            pass
        return sp500
    except Exception:
        return []


def _fetch_gb_tickers() -> List[str]:
    """Fetch FTSE 100 + FTSE 250 tickers from Wikipedia (appends .L suffix)."""
    tickers: List[str] = []
    urls = [
        "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "https://en.wikipedia.org/wiki/FTSE_250_Index",
    ]
    for url in urls:
        try:
            tables = pd.read_html(url, flavor="lxml")
            for tbl in tables:
                col = next(
                    (
                        c for c in tbl.columns
                        if any(k in str(c).lower() for k in ("ticker", "epic", "symbol"))
                    ),
                    None,
                )
                if col is None or len(tbl) < 10:
                    continue
                raw = [str(v).strip().replace(".", "-") for v in tbl[col].dropna()]
                valid = [
                    v + ".L" for v in raw
                    if 1 <= len(v) <= 8 and v.replace("-", "").isalnum()
                ]
                if len(valid) >= 10:
                    tickers.extend(valid)
                    break
        except Exception:
            pass
    return list(dict.fromkeys(tickers))


def _fetch_in_nse_tickers() -> List[str]:
    """Fetch ALL NSE-listed equities via the EQUITY_L.csv master list (~2100 stocks).

    Falls back to Nifty 500 CSV if the master list is unavailable.
    """
    hdr = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nseindia.com/",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers={"User-Agent": hdr["User-Agent"]}, timeout=10)
    except Exception:
        pass

    # Primary: full equity master list (all NSE-listed equities, EQ series)
    try:
        resp = session.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            headers=hdr, timeout=20,
        )
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        # Column ' SERIES' has a leading space
        series_col = next(c for c in df.columns if "series" in c.lower())
        sym_col = "SYMBOL"
        eq = df[df[series_col].str.strip() == "EQ"]
        tickers = [str(t).strip() + ".NS" for t in eq[sym_col].tolist() if str(t).strip()]
        if len(tickers) > 100:
            return tickers
    except Exception:
        pass

    # Fallback: Nifty 500 index constituents
    resp = session.get(
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        headers=hdr, timeout=20,
    )
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    col = next(c for c in df.columns if "symbol" in str(c).lower())
    return [str(t).strip() + ".NS" for t in df[col].tolist() if str(t).strip()]


_FETCHERS = {
    "US": _fetch_us_tickers,
    "GB": _fetch_gb_tickers,
    "IN_NSE": _fetch_in_nse_tickers,
}


def fetch_dynamic_universe(market_code: str) -> List[str]:
    """
    Return a comprehensive ticker list for *market_code*.

    For US, GB, and IN_NSE the list is fetched from public sources (Wikipedia /
    NSE India) and cached in memory for 24 hours.  All other markets (and any
    failed fetch) fall back to the hardcoded UNIVERSES list.
    """
    now = time.time()
    with _CACHE_LOCK:
        if market_code in _UNIVERSE_CACHE:
            cached, ts = _UNIVERSE_CACHE[market_code]
            if now - ts < _CACHE_TTL:
                return cached

    tickers: Optional[List[str]] = None
    if market_code in _FETCHERS:
        try:
            tickers = _FETCHERS[market_code]()
            if not tickers:
                tickers = None
        except Exception:
            tickers = None

    if tickers:
        with _CACHE_LOCK:
            _UNIVERSE_CACHE[market_code] = (tickers, now)
        return tickers

    return UNIVERSES.get(market_code, [])


def get_universe(market_code: str) -> List[str]:
    """Get comprehensive ticker list for a single market code."""
    return fetch_dynamic_universe(market_code)


def get_universe_for_markets(market_codes: List[str]) -> List[str]:
    """Return deduplicated ticker list for the given market codes."""
    tickers = []
    for code in market_codes:
        tickers.extend(get_universe(code))
    return list(dict.fromkeys(tickers))


def _to_float(v) -> Optional[float]:
    """Safely coerce a yfinance value to float; returns None for non-numeric or infinite values."""
    if v is None:
        return None
    try:
        result = float(v)
        if result != result or abs(result) == float("inf"):  # NaN or Inf
            return None
        return result
    except (ValueError, TypeError):
        return None


def _fetch_metrics(ticker: str) -> Optional[dict]:
    """Fetch fundamental metrics for one ticker via yfinance. Returns None on failure."""
    _rate_limit()
    try:
        info = yf.Ticker(ticker).info
        price = _to_float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if not price:
            return None

        de_raw = _to_float(info.get("debtToEquity"))
        de = de_raw / 100 if de_raw is not None else None

        def _pct(key) -> Optional[float]:
            v = _to_float(info.get(key))
            return round(v * 100, 2) if v is not None else None

        peg = _to_float(info.get("pegRatio"))
        if peg is None:
            pe = _to_float(info.get("trailingPE"))
            eg = _to_float(info.get("earningsGrowth"))
            if pe and eg and eg > 0:
                peg = round(pe / (eg * 100), 2)

        mktcap = _to_float(info.get("marketCap"))
        mktcap_b = round(mktcap / 1e9, 2) if mktcap else None

        return {
            "Ticker":         ticker,
            "Name":           info.get("shortName") or info.get("longName") or ticker,
            "Sector":         info.get("sector", "—"),
            "Market Cap (B)": mktcap_b,
            "P/E (TTM)":      _to_float(info.get("trailingPE")),
            "Fwd P/E":        _to_float(info.get("forwardPE")),
            "P/B":            _to_float(info.get("priceToBook")),
            "PEG":            peg,
            "ROE %":          _pct("returnOnEquity"),
            "ROA %":          _pct("returnOnAssets"),
            "Net Margin %":   _pct("profitMargins"),
            "Gross Margin %": _pct("grossMargins"),
            "Rev Growth %":   _pct("revenueGrowth"),
            "Earn Growth %":  _pct("earningsGrowth"),
            "D/E":            de,
            "Current Ratio":  _to_float(info.get("currentRatio")),
            "Div Yield %":    _pct("dividendYield"),
            "Currency":       info.get("currency", ""),
            "_price":         price,
            "_mktcap_raw":    mktcap,
        }
    except Exception:
        return None
    finally:
        _rate_release()


from src.yf_auth import warmup as _warmup_yfinance, rate_limit as _rate_limit, rate_release as _rate_release


def screen_stocks(
    tickers: List[str],
    filters: dict,
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    Fetch metrics for all tickers in parallel and apply filters.

    filters = {
        "P/E (TTM)":     (min_or_None, max_or_None),
        "ROE %":         (min_or_None, max_or_None),
        ...
    }
    progress_cb(done, total) is called after each ticker completes.
    """
    _warmup_yfinance()

    rows = []
    total = len(tickers)
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_metrics, t): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                rows.append(row)
            done += 1
            if progress_cb:
                progress_cb(done, total)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Apply numeric filters
    for col, (lo, hi) in filters.items():
        if col not in df.columns:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
        mask = pd.Series([True] * len(df), index=df.index)
        if lo is not None:
            mask &= df[col].isna() | (df[col] >= lo)
        if hi is not None:
            mask &= df[col].isna() | (df[col] <= hi)
        df = df[mask]

    # Sort by market cap desc
    df = df.sort_values("_mktcap_raw", ascending=False, na_position="last")
    df = df.drop(columns=["_mktcap_raw"], errors="ignore")
    return df.reset_index(drop=True)
