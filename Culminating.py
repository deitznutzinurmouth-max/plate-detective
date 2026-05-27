import pygame
import random
import math
import os
import sys
import json

def resource_path(relative_path):
    # When the game is packaged as an .exe by PyInstaller, files are stored
    # in a temporary folder (sys._MEIPASS). This function finds them there,
    # or falls back to the current directory when running as a normal .py file.
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ─────────────────────────────────────────────
# 1.  INIT & FULLSCREEN WINDOW
# ─────────────────────────────────────────────
pygame.init()

# Detect the monitor's native resolution so the game fills the screen exactly.
info       = pygame.display.Info()
V_WIDTH    = info.current_w
V_HEIGHT   = info.current_h
# FULLSCREEN | SCALED = true fullscreen that also scales content to fit the window.
screen     = pygame.display.set_mode((V_WIDTH, V_HEIGHT), pygame.FULLSCREEN | pygame.SCALED)
pygame.display.set_caption("Plate Detective")

# SX / SY are scale ratios: how much bigger/smaller this screen is vs the
# reference resolution of 1920x1080. S(v) converts any hardcoded pixel value
# so it looks the same on every screen size.
SX = V_WIDTH  / 1920
SY = V_HEIGHT / 1080

def S(v):
    # Scale a value proportionally to the screen size.
    # min(SX, SY) keeps things inside the screen without stretching.
    return int(v * min(SX, SY))

# ─────────────────────────────────────────────
# 2.  COLOUR PALETTE
# ─────────────────────────────────────────────
# All colours stored as (Red, Green, Blue) tuples, each 0–255.
C_BG      = (6,    8,   16)   # Very dark navy — the background
C_PANEL   = (14,  20,  38)    # Slightly lighter navy — panel backgrounds
C_ACCENT  = (0,  195, 255)    # Cyan — borders, highlights
C_WHITE   = (240, 242, 255)   # Slightly cool white — main text
C_GOLD    = (255, 210,   0)   # Gold — scores, titles
C_GREEN   = (0,  215,  95)    # Bright green — correct / Easy mode
C_RED     = (255,  55,  55)   # Red — wrong / Hard mode / game over
C_DIM     = (70,  85, 120)    # Muted blue-grey — secondary/hint text
C_BTN     = (28,  38,  65)    # Dark blue — button backgrounds

# ─────────────────────────────────────────────
# 3.  SOUND SYNTHESIS
# ─────────────────────────────────────────────
# All sounds are generated in code using math — no audio files needed.
# numpy lets us create arrays of audio samples and shape them into sounds.
SAMPLE_RATE = 44100   # 44,100 samples per second — standard CD quality
_SOUND_OK   = False
try:
    import numpy as np
    # Initialize the mixer: 16-bit signed audio, stereo, small buffer for low latency
    pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=1024)
    _SOUND_OK = True
except Exception:
    # If numpy isn't installed, we silently skip all sounds rather than crashing.
    pass

def _make_sound(mono):
    # Convert a 1D array of floats (-1.0 to 1.0) into a pygame Sound object.
    # 1. Clip values to [-1, 1] so we don't overflow the 16-bit audio range.
    # 2. Scale to 16-bit integers (-32767 to 32767).
    # 3. Duplicate the mono channel into stereo (left + right = same).
    pcm    = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)
    stereo = np.column_stack((pcm, pcm))
    return pygame.sndarray.make_sound(np.ascontiguousarray(stereo))

def _build_sounds():
    # Build all five sound effects using mathematical waveforms:
    #   - whoosh:   filtered noise with exponential decay (asteroid flying)
    #   - impact:   pitched thud + noise burst (asteroid landing)
    #   - correct:  four ascending musical notes (right answer)
    #   - wrong:    descending square wave (wrong answer)
    #   - time_up:  two-tone chord with fade in/out (timer expired)
    if not _SOUND_OK:
        return {}
    sounds = {}
    dur = 0.45;  t = np.linspace(0, dur, int(SAMPLE_RATE * dur))
    sounds["whoosh"] = _make_sound(np.random.uniform(-1,1,len(t)) *
                                   (np.sin(np.pi*t/dur)*0.7+0.3) *
                                   np.exp(-3*t) * 0.35)
    dur = 0.35;  t = np.linspace(0, dur, int(SAMPLE_RATE * dur))
    sounds["impact"]  = _make_sound((np.sin(2*np.pi*(120*np.exp(-8*t))*t)*0.7 +
                                     np.random.uniform(-1,1,len(t))*np.exp(-20*t)*0.3) *
                                    np.exp(-10*t)*0.6)
    dur = 0.7;   t = np.linspace(0, dur, int(SAMPLE_RATE * dur))
    wave = np.zeros(len(t)); seg = len(t)//4
    for i, freq in enumerate([523.25,659.25,783.99,1046.50]):
        sl=slice(i*seg,(i+1)*seg); tt=np.linspace(0,1,seg)
        wave[sl] += np.sin(2*np.pi*freq*t[sl])*np.exp(-4*tt)
    sounds["correct"] = _make_sound(wave*0.5)
    dur = 0.4;   t = np.linspace(0, dur, int(SAMPLE_RATE * dur))
    sounds["wrong"]   = _make_sound((np.sign(np.sin(2*np.pi*np.linspace(280,130,len(t))*t))*0.5 +
                                     np.random.uniform(-1,1,len(t))*0.15) *
                                    np.exp(-5*t)*0.55)
    dur = 0.55;  t = np.linspace(0, dur, int(SAMPLE_RATE * dur))
    env = np.ones(len(t)); fade = int(SAMPLE_RATE*0.15)
    env[:fade]=np.linspace(0,1,fade); env[-fade:]=np.linspace(1,0,fade)
    sounds["time_up"] = _make_sound((np.sin(2*np.pi*440*t)*0.5+np.sin(2*np.pi*330*t)*0.5)*env*0.6)
    return sounds

try:    SFX = _build_sounds()
except: SFX = {}

def play(name, volume=0.8):
    # Look up a sound by name and play it at the given volume (0.0–1.0).
    # Does nothing silently if sounds failed to load.
    s = SFX.get(name)
    if s:
        try: s.set_volume(volume); s.play()
        except: pass

# ─────────────────────────────────────────────
# 4.  DIFFICULTY SETTINGS
# ─────────────────────────────────────────────
# Each difficulty is a dictionary of tuning values:
#   attempts   = number of wrong guesses allowed (lives)
#   hit_zone   = how precise your click needs to be (fraction of map width)
#   speed      = how fast the asteroid flies toward the map
#   multiplier = score multiplier applied to each correct answer
#   time       = seconds allowed per round
#   color      = the UI accent color for that mode
DIFFICULTY = {
    "EASY":   {"attempts":7, "hit_zone":0.10, "speed":0.05, "multiplier":1, "time":45, "color":C_GREEN},
    "MEDIUM": {"attempts":5, "hit_zone":0.07, "speed":0.08, "multiplier":2, "time":30, "color":C_GOLD},
    "HARD":   {"attempts":3, "hit_zone":0.04, "speed":0.13, "multiplier":4, "time":20, "color":C_RED},
}
selected_difficulty = "MEDIUM"

# ─────────────────────────────────────────────
# 5.  LICENSE PLATE DESIGNS
# ─────────────────────────────────────────────
# Each entry is a dictionary describing how to visually draw that country's plate.
# Key fields:
#   bg          = plate background colour (RGB)
#   text        = main text colour (RGB)
#   border      = outer border/frame colour (RGB)
#   plate_text  = the example text shown on the plate
#   state_text  = optional sub-text (state/province name)
#   style       = which drawing routine to use (see Section 6)
#   strip_color = colour of the EU-style left strip (if any)
#   strip_code  = country code printed on the strip (e.g. "F", "D", "GB")
#   strip_flag  = list of (fraction, colour) pairs for flag-coloured strips
#   top_bar     = dict with a "colors" list for a striped bar across the top

PLATE_DESIGNS = {

    # ── NORTH AMERICA ──────────────────────────────────────────────────────
    "USA": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "ABC·1234", "state_text": "CALIFORNIA",
        "style": "usa",
        "top_bar": {"colors": [(0,0,150),(255,255,255),(220,0,0)]},
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Canada": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "AAAA·000", "state_text": "ONTARIO",
        "style": "canada",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Mexico": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,100,0),
        "plate_text": "ABC·12·34", "state_text": "MEXICO",
        "style": "mexico",
        "strip_color": None, "strip_code": None,
        "strip_flag": [(1/3,(0,100,0)),(1/3,(255,255,255)),(1/3,(180,0,0))],
    },

    # ── EU PLATES ──────────────────────────────────────────────────────────
    "UK": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,140),
        "plate_text": "AB12 CDE",
        "style": "eu_strip",
        "strip_color": (0,0,140), "strip_code": "GB",
        "strip_flag": None,
    },
    "France": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AB·123·CD",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "F",
        "strip_flag": None,
    },
    "Germany": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "B · AB 1234",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "D",
        "strip_flag": None,
    },
    "Italy": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AB 123 CD",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "I",
        "strip_flag": None,
    },
    "Spain": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "1234 ABC",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "E",
        "strip_flag": None,
    },
    "Sweden": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "ABC 123",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "S",
        "strip_flag": None,
    },
    "Poland": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "WA 12345",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "PL",
        "strip_flag": None,
    },
    "Ukraine": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,87,183),
        "plate_text": "AA 1234 BB",
        "style": "eu_strip",
        "strip_color": (0,87,183), "strip_code": "UA",
        "strip_flag": None,
    },
    "Iceland": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "ABC 12",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "IS",
        "strip_flag": None,
    },
    "Luxembourg": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AB 1234",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "L",
        "strip_flag": None,
    },
    "Malta": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "ABC 123",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "M",
        "strip_flag": None,
    },
    "Albania": {
        "bg": (255,255,255), "text": (0,0,0), "border": (190,0,0),
        "plate_text": "AA 001 BB",
        "style": "eu_strip",
        "strip_color": (190,0,0), "strip_code": "AL",
        "strip_flag": None,
    },
    "Estonia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "000 AAA",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "EST",
        "strip_flag": None,
    },
    "Latvia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AA 0000",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "LV",
        "strip_flag": None,
    },
    "Lithuania": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AAA 000",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "LT",
        "strip_flag": None,
    },
    "Belarus": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "0000 AA-1",
        "style": "flag_strip_right",
        "strip_color": None, "strip_code": "BY",
        "strip_flag": [(0.5,(200,50,0)),(0.5,(0,130,60))],
    },
    "Moldova": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AA 000 AA",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "MD",
        "strip_flag": None,
    },
    "Bosnia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,60,160),
        "plate_text": "A00-A-000",
        "style": "eu_strip",
        "strip_color": (0,60,160), "strip_code": "BIH",
        "strip_flag": None,
    },
    "Montenegro": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "AB 000 CD",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "MNE",
        "strip_flag": None,
    },
    "North Macedonia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,50,0),
        "plate_text": "SK 0000 AA",
        "style": "eu_strip",
        "strip_color": (220,50,0), "strip_code": "MK",
        "strip_flag": None,
    },
    "Kosovo": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,60,160),
        "plate_text": "01 000 AA",
        "style": "eu_strip",
        "strip_color": (0,60,160), "strip_code": "RKS",
        "strip_flag": None,
    },

    # ── EASTERN EUROPE / CIS ────────────────────────────────────────────────
    "Russia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "А 123 ВС 77",
        "style": "russia",
        "strip_color": None, "strip_code": "RUS",
        "strip_flag": [(1/3,(255,255,255)),(1/3,(0,57,166)),(1/3,(213,43,30))],
    },
    "Georgia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "AAA-000",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "GE",
        "strip_flag": None,
    },
    "Armenia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "00 AA 000",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "AM",
        "strip_flag": None,
    },
    "Azerbaijan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,100,50),
        "plate_text": "10 AA 000",
        "style": "eu_strip",
        "strip_color": (0,100,50), "strip_code": "AZ",
        "strip_flag": None,
    },
    "Kazakhstan": {
        "bg": (135,206,235), "text": (255,220,0), "border": (255,220,0),
        "plate_text": "123 AA 01",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Uzbekistan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,60),
        "plate_text": "01 A 000 BA",
        "style": "eu_strip",
        "strip_color": (0,130,60), "strip_code": "UZ",
        "strip_flag": None,
    },
    "Tajikistan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,100,180),
        "plate_text": "0000 TJ-1",
        "style": "eu_strip",
        "strip_color": (0,100,180), "strip_code": "TJ",
        "strip_flag": None,
    },
    "Turkmenistan": {
        "bg": (0,150,70), "text": (255,255,255), "border": (255,255,255),
        "plate_text": "01 AA 00",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Kyrgyzstan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "0001 KG 7",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "KG",
        "strip_flag": None,
    },
    "Mongolia": {
        "bg": (200,0,0), "text": (255,220,0), "border": (255,220,0),
        "plate_text": "УНА 1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── MIDDLE EAST ─────────────────────────────────────────────────────────
    "Turkey": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "34 ABC 12",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "TR",
        "strip_flag": None,
    },
    "Saudi Arabia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,0),
        "plate_text": "أ ب ج · 1234",
        "style": "arabic_right",
        "strip_color": (0,130,0), "strip_code": "KSA",
        "strip_flag": None,
    },
    "Iraq": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "ب · 12345",
        "style": "iraq",
        "strip_color": None, "strip_code": None,
        "strip_flag": [(1/3,(0,0,0)),(1/3,(255,255,255)),(1/3,(206,17,38))],
        "top_bar": {"colors": [(0,0,0),(255,255,255),(206,17,38)]},
    },
    "Egypt": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "أ · 12345",
        "style": "arabic_right",
        "strip_color": (220,0,0), "strip_code": "ET",
        "strip_flag": None,
    },

    # ── EAST ASIA ───────────────────────────────────────────────────────────
    "China": {
        "bg": (0,0,160), "text": (255,255,255), "border": (220,0,0),
        "plate_text": "沪A · 12345",
        "style": "china",
        "strip_color": (220,0,0), "strip_code": None,
        "strip_flag": None,
    },
    "Japan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,100,0),
        "plate_text": "品川 300\nあ 12-34",
        "style": "japan",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "South Korea": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "서울 12가 3456",
        "style": "korea",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── SOUTH ASIA ──────────────────────────────────────────────────────────
    "India": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "MH 01 AB 1234",
        "style": "india",
        "strip_color": (0,0,160), "strip_code": "IND",
        "strip_flag": None,
    },
    "Pakistan": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,50),
        "plate_text": "LHR-1234",
        "style": "eu_strip",
        "strip_color": (0,130,50), "strip_code": "PK",
        "strip_flag": None,
    },
    "Bangladesh": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,50),
        "plate_text": "DHAKA-KA-1234",
        "style": "eu_strip",
        "strip_color": (0,130,50), "strip_code": "BD",
        "strip_flag": None,
    },
    "Sri Lanka": {
        "bg": (255,255,255), "text": (0,0,0), "border": (180,20,0),
        "plate_text": "CAB-1234",
        "style": "eu_strip",
        "strip_color": (180,20,0), "strip_code": "SRL",
        "strip_flag": None,
    },
    "Nepal": {
        "bg": (255,255,255), "text": (0,0,0), "border": (180,0,0),
        "plate_text": "BA 1 PA 001",
        "style": "eu_strip",
        "strip_color": (180,0,0), "strip_code": "NEP",
        "strip_flag": None,
    },
    "Bhutan": {
        "bg": (255,200,0), "text": (0,0,0), "border": (220,80,0),
        "plate_text": "BT-1-A-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Maldives": {
        "bg": (0,100,60), "text": (255,255,255), "border": (255,255,255),
        "plate_text": "MLE-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── SOUTHEAST ASIA ──────────────────────────────────────────────────────
    "Vietnam": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,180),
        "plate_text": "51A-12345",
        "style": "vietnam",
        "strip_color": (220,0,0), "strip_code": None,
        "strip_flag": None,
    },
    "Thailand": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "กข 1234",
        "style": "thailand",
        "strip_color": None, "strip_code": None,
        "strip_flag": None,
        "state_text": "กรุงเทพ",
        "top_bar": {"colors": [(220,0,0),(255,255,255),(0,0,160),(255,255,255),(220,0,0)]},
    },
    "Malaysia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "WA 1234 A",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "MAL",
        "strip_flag": None,
    },
    "Indonesia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "B 1234 ABC",
        "style": "eu_strip",
        "strip_color": (220,0,0), "strip_code": "RI",
        "strip_flag": None,
    },
    "Myanmar": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "1A-1234",
        "style": "eu_strip",
        "strip_color": (0,100,50), "strip_code": "MYA",
        "strip_flag": None,
    },
    "Laos": {
        "bg": (220,0,0), "text": (255,255,255), "border": (0,0,180),
        "plate_text": "1234 ກ",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Cambodia": {
        "bg": (0,0,180), "text": (255,255,255), "border": (0,0,0),
        "plate_text": "1A-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Timor-Leste": {
        "bg": (220,0,0), "text": (255,255,255), "border": (255,255,0),
        "plate_text": "1A-12-34",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── SOUTH AMERICA ───────────────────────────────────────────────────────
    "Brazil": {
        "bg": (0,130,0), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "ABC-1D23",
        "style": "brazil",
        "strip_color": None, "strip_code": "BR",
        "state_text": "SP",
        "strip_flag": None,
    },
    "Argentina": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "AB 001 CD",
        "style": "mercosur",
        "strip_color": (0,120,220), "strip_code": "RA",
        "strip_flag": None,
    },
    "Colombia": {
        "bg": (255,220,0), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "ABC-123",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Venezuela": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,180),
        "plate_text": "AB1-23C",
        "style": "eu_strip",
        "strip_color": (0,0,180), "strip_code": "YV",
        "strip_flag": None,
    },
    "Peru": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "A1B-234",
        "style": "peru",
        "strip_color": (220,0,0), "strip_code": "PE",
        "strip_flag": None,
    },
    "Suriname": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,160,0),
        "plate_text": "AB-1234",
        "style": "eu_strip",
        "strip_color": (0,160,0), "strip_code": "SME",
        "strip_flag": None,
    },
    "Guyana": {
        "bg": (0,130,50), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "PAA 1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── AFRICA ──────────────────────────────────────────────────────────────
    "Nigeria": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,0),
        "plate_text": "ABC 123 DE",
        "style": "eu_strip",
        "strip_color": (0,130,0), "strip_code": "WN",
        "state_text": "LAGOS",
        "strip_flag": None,
    },
    "South Africa": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "CA 123 456",
        "style": "eu_strip",
        "strip_color": (0,0,160), "strip_code": "ZA",
        "strip_flag": None,
    },
    "Morocco": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,130,0),
        "plate_text": "12345 | أ",
        "style": "arabic_right",
        "strip_color": (220,0,0), "strip_code": "MA",
        "strip_flag": None,
    },
    "Kenya": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "KAA 001A",
        "style": "eu_strip",
        "strip_color": (0,130,0), "strip_code": "EAK",
        "strip_flag": None,
    },
    "Eritrea": {
        "bg": (0,150,0), "text": (255,255,255), "border": (0,0,0),
        "plate_text": "A-12345",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Djibouti": {
        "bg": (0,150,180), "text": (255,255,255), "border": (0,0,0),
        "plate_text": "DJ-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Burundi": {
        "bg": (255,255,255), "text": (0,0,0), "border": (220,0,0),
        "plate_text": "AB-1234",
        "style": "eu_strip",
        "strip_color": (0,130,0), "strip_code": "RU",
        "strip_flag": None,
    },
    "Rwanda": {
        "bg": (0,100,180), "text": (255,255,255), "border": (0,0,0),
        "plate_text": "RAA 001 A",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Lesotho": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,180),
        "plate_text": "ABC 001",
        "style": "eu_strip",
        "strip_color": (0,130,0), "strip_code": "LS",
        "strip_flag": None,
    },
    "Eswatini": {
        "bg": (0,0,180), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "SD 1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Comoros": {
        "bg": (0,150,70), "text": (255,255,255), "border": (255,255,255),
        "plate_text": "KM-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Cape Verde": {
        "bg": (0,60,150), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "AA-12-AA",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Sao Tome": {
        "bg": (0,130,0), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "ST-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Seychelles": {
        "bg": (0,60,200), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "S12345",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },

    # ── PACIFIC / OCEANIA ───────────────────────────────────────────────────
    "Australia": {
        "bg": (255,255,255), "text": (0,0,0), "border": (0,0,160),
        "plate_text": "ABC · 12D",
        "style": "australia",
        "strip_color": None, "strip_code": None,
        "state_text": "NSW",
        "strip_flag": None,
    },
    "Vanuatu": {
        "bg": (0,130,70), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "VU-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Samoa": {
        "bg": (0,0,180), "text": (255,255,255), "border": (220,0,0),
        "plate_text": "WS-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Tonga": {
        "bg": (220,0,0), "text": (255,255,255), "border": (0,0,0),
        "plate_text": "TO 1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Kiribati": {
        "bg": (0,0,180), "text": (255,255,255), "border": (220,0,0),
        "plate_text": "KI-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Palau": {
        "bg": (0,180,220), "text": (255,220,0), "border": (0,0,0),
        "plate_text": "PW-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Nauru": {
        "bg": (0,0,180), "text": (255,255,255), "border": (255,200,0),
        "plate_text": "NR-001",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Tuvalu": {
        "bg": (0,180,220), "text": (0,0,0), "border": (0,0,0),
        "plate_text": "TV-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Marshall Islands": {
        "bg": (0,0,180), "text": (255,255,255), "border": (220,160,0),
        "plate_text": "MH-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
    "Micronesia": {
        "bg": (0,180,220), "text": (255,255,255), "border": (255,255,255),
        "plate_text": "FSM-1234",
        "style": "plain",
        "strip_color": None, "strip_code": None, "strip_flag": None,
    },
}

def get_plate_design(country):
    # Return the design dict for a given country name.
    # If the country isn't in PLATE_DESIGNS, return a generic white plate
    # using the first 3 letters of the country name as the strip code.
    return PLATE_DESIGNS.get(country, {
        "bg":(255,255,255),"text":(0,0,0),"border":(0,0,0),
        "plate_text":"AA-1234","state_text":None,"style":"plain",
        "strip_color":(0,0,160),"strip_code":country[:3].upper(),"strip_flag":None,
    })


# ─────────────────────────────────────────────
# 6.  LICENSE PLATE DRAWING
# ─────────────────────────────────────────────

def _draw_bolt(surface, x, y, r):
    # Draw a screw bolt: a grey circle with a darker ring to simulate depth.
    pygame.draw.circle(surface, (160,160,160), (x, y), r)
    pygame.draw.circle(surface, (100,100,100), (x, y), r, max(1,r//3))


def draw_eu_strip(surface, px, py, pw, ph, strip_color, code, font):
    # Draw the standard EU blue strip on the left side of a plate.
    # Contains a ring of 12 gold stars and the country code below them.
    sw = S(55)
    # Draw the blue strip as two rects: one rounded left, one square right edge
    # so it blends flush into the plate body.
    pygame.draw.rect(surface, strip_color, (px, py, sw, ph), border_radius=S(8))
    pygame.draw.rect(surface, strip_color, (px + sw//2, py, sw//2, ph))
    cx_stars = px + sw // 2
    # Place 12 stars evenly around a circle using trigonometry.
    for i in range(12):
        ang = math.pi/2 + 2*math.pi*i/12
        sx = int(cx_stars + S(18)*math.cos(ang))
        sy = int(py + ph//2 - S(14) + S(14)*math.sin(ang))
        pygame.draw.circle(surface, (255,210,0), (sx,sy), max(1,S(2)))
    if code:
        lbl = font.render(code, True, (255,255,255))
        surface.blit(lbl, lbl.get_rect(centerx=cx_stars, centery=py + ph - S(14)))
    return sw  # Return strip width so the caller knows where the plate text should start


def draw_license_plate(surface, country, cx, cy, plate_font, small_font):
    # Main plate drawing function. Looks up the design for the given country,
    # draws the shared base (shadow, outer border, background, bolts),
    # then delegates to a style-specific branch for unique features.

    d = get_plate_design(country)
    style = d["style"]

    # pw/ph = plate width/height. px/py = top-left corner of the plate.
    pw, ph = S(520), S(130)
    px, py = cx - pw//2, cy - ph//2
    bg     = d["bg"]     # plate background colour
    tc     = d["text"]   # text colour
    bc     = d["border"] # border colour
    pt     = d.get("plate_text", "AA-1234")
    st     = d.get("state_text", None)

    # ── Drop shadow: a semi-transparent dark rectangle slightly offset ──
    shad = pygame.Surface((pw+S(8), ph+S(8)), pygame.SRCALPHA)
    pygame.draw.rect(shad, (0,0,0,70), (0,0,pw+S(8),ph+S(8)), border_radius=S(12))
    surface.blit(shad, (px+S(3)-S(4), py+S(3)-S(4)))

    # ── Outer border frame ──
    border_outer = pygame.Rect(px-S(7), py-S(7), pw+S(14), ph+S(14))
    pygame.draw.rect(surface, bc, border_outer, border_radius=S(15))
    # Subtle inner highlight makes the border look 3D/embossed.
    hi_col = tuple(min(255, c+50) for c in bc)
    pygame.draw.rect(surface, hi_col, border_outer.inflate(-S(4),-S(4)), width=S(2), border_radius=S(13))

    # ── Plate background ──
    plate_rect = pygame.Rect(px, py, pw, ph)
    pygame.draw.rect(surface, bg, plate_rect, border_radius=S(8))

    # ── Four corner bolts (drawn on top of background so they're visible) ──
    for bx, by in [(px+S(12),py+S(12)), (px+pw-S(12),py+S(12)),
                   (px+S(12),py+ph-S(12)), (px+pw-S(12),py+ph-S(12))]:
        _draw_bolt(surface, bx, by, S(5))

    # ── Style-specific drawing ──
    # Each branch handles a different plate layout (EU strip, top bar, etc.)

    if style == "eu_strip":
        # Standard European plate: blue strip on the left, text to the right.
        sc = d.get("strip_color") or (0,0,160)
        code = d.get("strip_code")
        sw = draw_eu_strip(surface, px, py, pw, ph, sc, code, small_font)
        # Center the text in the remaining space to the right of the strip.
        text_cx = px + sw + (pw - sw)//2
        if st:
            sl = small_font.render(st, True, C_DIM)
            surface.blit(sl, sl.get_rect(right=px+pw-S(18), y=py+S(6)))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=text_cx, centery=cy))

    elif style == "plain":
        # Simplest style: just centered text, no strips or bars.
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=cx, centery=cy))

    elif style == "usa":
        # USA plate: thin tricolor bar across the top (e.g. blue/white/red),
        # state name in small text below it, plate number centered.
        top_bar = d.get("top_bar")
        if top_bar:
            bar_h = S(9)
            total = len(top_bar["colors"])
            seg_w = pw // total
            # Draw each color segment side by side. +1 on width closes gaps.
            for i, col in enumerate(top_bar["colors"]):
                pygame.draw.rect(surface, col, (px + i*seg_w, py, seg_w+1, bar_h))
            # Redraw the background below the bar, then re-stamp bolts on top.
            pygame.draw.rect(surface, bg, (px, py+bar_h, pw, ph-bar_h))
            for bx2, by2 in [(px+S(12),py+S(12)),(px+pw-S(12),py+S(12)),
                              (px+S(12),py+ph-S(12)),(px+pw-S(12),py+ph-S(12))]:
                _draw_bolt(surface, bx2, by2, S(5))
        if st:
            # State name in small blue text near the top
            sl = small_font.render(st, True, (80,80,180))
            surface.blit(sl, sl.get_rect(centerx=cx, y=py+S(8)))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(8)))

    elif style == "canada":
        # Canadian plate: province name at top in red, plate number slightly
        # left of center, and a small maple leaf polygon on the right.
        if st:
            sl = small_font.render(st, True, (180,0,0))
            surface.blit(sl, sl.get_rect(centerx=cx, y=py+S(6)))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=cx - S(18), centery=cy+S(6)))
        lx, ly = cx + S(190), cy
        leaf_size = S(18)
        import math as _m
        pts = []
        # Build a 10-point star polygon approximating a maple leaf.
        # Alternates between outer (leaf_size) and inner (leaf_size*0.45) radii.
        for step in range(10):
            ang = _m.pi/2 + 2*_m.pi*step/10
            r   = leaf_size if step % 2 == 0 else leaf_size*0.45
            pts.append((int(lx + r*_m.cos(ang)), int(ly - r*_m.sin(ang))))
        if len(pts) > 2:
            pygame.draw.polygon(surface, (180,0,0), pts)

    elif style == "mexico":
        # Mexican plate: thin green stripe on left, red stripe on right,
        # state name at top center, plate number below.
        stripe_w = S(20)
        pygame.draw.rect(surface, (0,120,0), (px, py, stripe_w, ph))
        pygame.draw.rect(surface, (180,0,0), (px+pw-stripe_w, py, stripe_w, ph))
        for bx2, by2 in [(px+S(12),py+S(12)),(px+pw-S(12),py+S(12)),
                          (px+S(12),py+ph-S(12)),(px+pw-S(12),py+ph-S(12))]:
            _draw_bolt(surface, bx2, by2, S(5))
        if st:
            sl = small_font.render(st, True, (0,100,0))
            surface.blit(sl, sl.get_rect(centerx=cx, y=py+S(5)))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(8)))

    elif style == "russia":
        # Russian plate: plate number on left, vertical tricolor flag strip
        # on the right with region code and "RUS" below it.
        rw = S(68)
        rpx = px + pw - rw - S(4)
        seg_h = ph // 3
        # Draw the three horizontal bands of the Russian flag (white/blue/red).
        for i, col in enumerate([(255,255,255),(0,57,166),(213,43,30)]):
            pygame.draw.rect(surface, col, (rpx, py+i*seg_h, rw, seg_h+2))
        pygame.draw.line(surface, (180,180,180), (rpx, py), (rpx, py+ph), S(2))
        reg = small_font.render("77", True, (0,0,0))
        surface.blit(reg, reg.get_rect(centerx=rpx+rw//2, centery=cy))
        rus = small_font.render("RUS", True, (0,50,160))
        surface.blit(rus, rus.get_rect(centerx=rpx+rw//2, y=cy+S(14)))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=px+(pw-rw)//2-S(8), centery=cy))

    elif style == "flag_strip_right":
        # Flag strip on the RIGHT side (e.g. Belarus).
        # strip_flag is a list of (fraction, color) pairs that stack vertically.
        rw = S(62)
        rpx = px + pw - rw - S(4)
        fracs = d.get("strip_flag", [(0.5,(200,50,0)),(0.5,(0,130,60))])
        y_cur = py
        for frac, col in fracs:
            h = int(ph * frac)
            pygame.draw.rect(surface, col, (rpx, y_cur, rw, h+1))
            y_cur += h
        pygame.draw.line(surface, (180,180,180), (rpx, py), (rpx, py+ph), S(2))
        code = d.get("strip_code","")
        if code:
            cl = small_font.render(code, True, (255,255,255))
            surface.blit(cl, cl.get_rect(centerx=rpx+rw//2, centery=cy))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=(px + rpx)//2, centery=cy))

    elif style == "china":
        # Chinese plate: dark blue background, red left strip with a 5-point
        # yellow star, thin separator line, then white plate text.
        epw = S(48)
        pygame.draw.rect(surface, (220,0,0), (px, py, epw, ph), border_radius=S(6))
        pygame.draw.rect(surface, (220,0,0), (px+epw//2, py, epw//2, ph))
        # Draw a 5-pointed star using alternating outer/inner radius points.
        pts10 = []
        for i in range(10):
            ang = math.pi/2 + math.pi*i/5
            r = S(12) if i%2==0 else S(5)
            pts10.append((int(px+epw//2 + r*math.cos(ang)), int(cy - r*math.sin(ang))))
        if len(pts10) > 2:
            pygame.draw.polygon(surface, (255,220,0), pts10)
        pygame.draw.line(surface, (150,150,255), (px+epw, py+S(4)), (px+epw, py+ph-S(4)), S(2))
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=px+epw+(pw-epw)//2, centery=cy))

    elif style == "japan":
        # Japanese plate: thin green border bars top and bottom, two lines of
        # text (region/class on top, kana + number on bottom).
        pygame.draw.rect(surface, (0,100,0), (px+S(4), py+S(4), pw-S(8), S(6)))
        pygame.draw.rect(surface, (0,100,0), (px+S(4), py+ph-S(10), pw-S(8), S(6)))
        lines = pt.split("\n")
        if len(lines) == 2:
            l1 = small_font.render(lines[0], True, (0,0,0))
            surface.blit(l1, l1.get_rect(centerx=cx, y=py+S(12)))
            l2 = plate_font.render(lines[1], True, (0,0,0))
            surface.blit(l2, l2.get_rect(centerx=cx, y=py+S(38)))
        else:
            t = plate_font.render(pt, True, (0,0,0))
            surface.blit(t, t.get_rect(centerx=cx, centery=cy))

    elif style == "korea":
        # South Korean plate: thin blue bar at the top, large centered text.
        pygame.draw.rect(surface, (0,0,180), (px+S(4), py+S(4), pw-S(8), S(7)))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(6)))

    elif style == "india":
        # Indian plate: Ashoka Chakra (blue wheel with 24 spokes) on the left,
        # "IND" strip on the right, plate text in the center.
        ec = (px+S(32), cy)
        pygame.draw.circle(surface, (0,0,180), ec, S(18))
        pygame.draw.circle(surface, (255,255,255), ec, S(14), S(2))
        # Draw 24 spokes radiating from the center of the wheel.
        for i in range(24):
            ang = 2*math.pi*i/24
            x1 = int(ec[0]+S(5)*math.cos(ang)); y1 = int(ec[1]+S(5)*math.sin(ang))
            x2 = int(ec[0]+S(12)*math.cos(ang)); y2 = int(ec[1]+S(12)*math.sin(ang))
            pygame.draw.line(surface, (255,255,255), (x1,y1),(x2,y2), 1)
        bw2 = S(52)
        pygame.draw.rect(surface, (0,0,180), (px+pw-bw2-S(4), py, bw2, ph), border_radius=S(6))
        pygame.draw.rect(surface, (0,0,180), (px+pw-bw2-S(4), py, bw2//2, ph))
        ind = small_font.render("IND", True, (255,255,255))
        surface.blit(ind, ind.get_rect(centerx=px+pw-bw2//2-S(4), centery=cy))
        t = plate_font.render(pt, True, (0,0,0))
        text_area_cx = (px+S(50)+px+pw-bw2-S(4))//2
        surface.blit(t, t.get_rect(centerx=text_area_cx, centery=cy))

    elif style == "brazil":
        # Brazilian Mercosul plate: green header bar with "BRASIL · SP",
        # plate number in white below.
        header_h = S(28)
        pygame.draw.rect(surface, (0,100,0), (px, py, pw, header_h), border_radius=S(8))
        pygame.draw.rect(surface, (0,100,0), (px, py+header_h//2, pw, header_h//2))
        code = d.get("strip_code","BR")
        br_lbl = small_font.render(f"BRASIL · {d.get('state_text','SP')}", True, (255,255,255))
        surface.blit(br_lbl, br_lbl.get_rect(centerx=cx, centery=py+header_h//2))
        t = plate_font.render(pt, True, (255,255,255))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(8)))

    elif style == "mercosur":
        # Argentine Mercosur plate: blue header bar with "MERCOSUR · ARGENTINA · RA",
        # black plate number below.
        header_h = S(28)
        sc = d.get("strip_color", (0,120,220))
        pygame.draw.rect(surface, sc, (px, py, pw, header_h), border_radius=S(8))
        pygame.draw.rect(surface, sc, (px, py+header_h//2, pw, header_h//2))
        code = d.get("strip_code","RA")
        hdr = small_font.render(f"MERCOSUR · ARGENTINA · {code}", True, (255,255,255))
        surface.blit(hdr, hdr.get_rect(centerx=cx, centery=py+header_h//2))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(10)))

    elif style == "peru":
        # Peruvian plate: red vertical stripes on both the left and right edges,
        # white center with black text (mirrors the Peruvian flag).
        sw2 = S(22)
        pygame.draw.rect(surface, (220,0,0), (px, py, sw2, ph), border_radius=S(8))
        pygame.draw.rect(surface, (220,0,0), (px+sw2//2, py, sw2//2, ph))
        pygame.draw.rect(surface, (220,0,0), (px+pw-sw2, py, sw2, ph), border_radius=S(8))
        pygame.draw.rect(surface, (220,0,0), (px+pw-sw2, py, sw2//2, ph))
        for bx2, by2 in [(px+S(12),py+S(12)),(px+pw-S(12),py+S(12)),
                          (px+S(12),py+ph-S(12)),(px+pw-S(12),py+ph-S(12))]:
            _draw_bolt(surface, bx2, by2, S(5))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy))

    elif style == "vietnam":
        # Vietnamese plate: red left strip with a 5-point yellow star (similar
        # to the Chinese style), separator line, then black text on white.
        sw2 = S(48)
        pygame.draw.rect(surface, (220,0,0), (px, py, sw2, ph), border_radius=S(6))
        pygame.draw.rect(surface, (220,0,0), (px+sw2//2, py, sw2//2, ph))
        pts5 = []
        for i in range(10):
            ang = math.pi/2 + math.pi*i/5
            r = S(14) if i%2==0 else S(6)
            pts5.append((int(px+sw2//2 + r*math.cos(ang)), int(cy - r*math.sin(ang))))
        if len(pts5) > 2:
            pygame.draw.polygon(surface, (255,220,0), pts5)
        pygame.draw.line(surface, (180,180,255), (px+sw2, py+S(4)), (px+sw2, py+ph-S(4)), S(2))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=px+sw2+(pw-sw2)//2, centery=cy))

    elif style == "thailand":
        # Thai plate: 5-color bar across the top (red/white/blue/white/red —
        # the Thai flag), province name at the bottom, plate text in the middle.
        top_bar = d.get("top_bar")
        if top_bar:
            total = len(top_bar["colors"])
            bar_h = S(8)
            seg_w = pw // total
            for i, col in enumerate(top_bar["colors"]):
                x_off = px + i*seg_w
                # Last segment gets remaining pixels to avoid rounding gaps.
                w_off = seg_w+1 if i < total-1 else pw-i*seg_w
                pygame.draw.rect(surface, col, (x_off, py, w_off, bar_h))
        if st:
            sl = small_font.render(st, True, (0,0,180))
            surface.blit(sl, sl.get_rect(centerx=cx, y=py+ph-S(24)))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy - S(4)))

    elif style == "australia":
        # Australian plate: state name at top, plate text below, small blue
        # circle in the top-right corner (representing the Southern Cross badge).
        if st:
            sl = small_font.render(st, True, (0,0,160))
            surface.blit(sl, sl.get_rect(centerx=cx, y=py+S(6)))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(8)))
        pygame.draw.circle(surface, (0,0,160), (px+pw-S(22), py+S(18)), S(8))

    elif style == "arabic_right":
        # Middle Eastern plates (Saudi Arabia, Egypt, Morocco): colored strip
        # on the RIGHT side with the country code, Arabic text on the left.
        sc = d.get("strip_color") or (0,130,0)
        code = d.get("strip_code","")
        rw2 = S(62)
        rpx2 = px + pw - rw2
        pygame.draw.rect(surface, sc, (rpx2, py, rw2, ph), border_radius=S(8))
        pygame.draw.rect(surface, sc, (rpx2, py, rw2//2, ph))
        if code:
            cl = small_font.render(code, True, (255,255,255))
            surface.blit(cl, cl.get_rect(centerx=rpx2+rw2//2, centery=cy))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=(px+rpx2)//2, centery=cy))

    elif style == "iraq":
        # Iraqi plate: black/white/red tricolor bar across the top (Iraqi flag
        # colors), then centered Arabic text below.
        top_bar = d.get("top_bar")
        if top_bar:
            bar_h = S(9)
            total = len(top_bar["colors"])
            seg_w = pw // total
            for i, col in enumerate(top_bar["colors"]):
                pygame.draw.rect(surface, col, (px + i*seg_w, py, seg_w+1, bar_h))
        t = plate_font.render(pt, True, (0,0,0))
        surface.blit(t, t.get_rect(centerx=cx, centery=cy+S(6)))

    else:
        # Fallback: plain centered text for any unrecognized style.
        t = plate_font.render(pt, True, tc)
        surface.blit(t, t.get_rect(centerx=cx, centery=cy))

    # ── Final border outline drawn last so it sits on top of everything ──
    pygame.draw.rect(surface, bc, plate_rect, width=S(3), border_radius=S(8))


# ─────────────────────────────────────────────
# 7.  COUNTRY COORDINATES
# ─────────────────────────────────────────────
def ll(lon, lat):
    # Convert real-world longitude/latitude into a (0.0–1.0, 0.0–1.0) position
    # on the world map image. (0,0) = top-left (near 180°W, 90°N).
    # Formula: x = (lon + 180) / 360,  y = (90 - lat) / 180
    return (round((lon+180)/360,4), round((90-lat)/180,4))

# Three pools of countries — Easy is a subset of Medium, Medium of Hard.
# This means unlocking a harder mode adds new countries without losing old ones.
COUNTRIES_EASY = {
    "USA":ll(-98.58,39.83),"Canada":ll(-96.80,60.00),"Brazil":ll(-51.93,-14.24),
    "France":ll(2.35,46.23),"Germany":ll(10.45,51.17),"Russia":ll(99.00,61.52),
    "China":ll(104.20,35.86),"India":ll(78.96,20.59),"Australia":ll(133.78,-25.27),
    "Mexico":ll(-102.55,23.63),"UK":ll(-3.44,55.38),"Japan":ll(138.25,36.20),
    "Italy":ll(12.57,41.87),"Spain":ll(-3.75,40.46),"Argentina":ll(-63.62,-38.42),
}
COUNTRIES_MEDIUM = {**COUNTRIES_EASY,   # Inherit all Easy countries, then add more
    "South Korea":ll(127.77,35.91),"Turkey":ll(35.24,38.96),"Egypt":ll(30.80,26.82),
    "Nigeria":ll(8.68,9.08),"South Africa":ll(25.08,-29.00),"Saudi Arabia":ll(45.08,23.89),
    "Indonesia":ll(113.92,-0.79),"Colombia":ll(-74.30,4.57),"Ukraine":ll(31.17,49.00),
    "Poland":ll(19.14,51.92),"Sweden":ll(18.64,60.13),"Pakistan":ll(69.35,30.38),
    "Vietnam":ll(108.28,14.06),"Iraq":ll(43.68,33.22),"Peru":ll(-75.01,-9.19),
    "Venezuela":ll(-66.59,6.42),"Kenya":ll(37.91,-0.02),"Morocco":ll(-7.09,31.79),
    "Thailand":ll(101.00,15.87),"Malaysia":ll(109.70,3.12),
}
COUNTRIES_HARD = {**COUNTRIES_MEDIUM,   # Inherit all Medium countries, then add more
    "Nepal":ll(84.12,28.39),"Mongolia":ll(103.85,46.86),"Laos":ll(102.50,17.97),
    "Cambodia":ll(104.99,12.57),"Myanmar":ll(95.96,16.87),"Bangladesh":ll(90.36,23.68),
    "Sri Lanka":ll(80.77,7.87),"Kazakhstan":ll(66.92,48.02),"Uzbekistan":ll(63.95,41.38),
    "Azerbaijan":ll(47.58,40.14),"Georgia":ll(43.36,42.32),"Armenia":ll(44.56,40.07),
    "Belarus":ll(27.95,53.71),"Moldova":ll(28.37,47.41),"Albania":ll(20.17,41.15),
    "North Macedonia":ll(21.75,41.61),"Kosovo":ll(20.90,42.60),"Bosnia":ll(17.68,44.17),
    "Montenegro":ll(19.37,42.71),"Estonia":ll(25.01,58.60),"Latvia":ll(24.75,56.88),
    "Lithuania":ll(23.88,55.17),"Luxembourg":ll(6.13,49.82),"Malta":ll(14.38,35.94),
    "Iceland":ll(-18.49,64.96),"Bhutan":ll(90.43,27.51),"Maldives":ll(73.22,3.20),
    "Timor-Leste":ll(125.73,-8.87),"Suriname":ll(-56.00,3.92),"Guyana":ll(-59.79,4.86),
    "Tajikistan":ll(71.28,38.86),"Turkmenistan":ll(58.38,38.97),"Kyrgyzstan":ll(74.77,41.21),
    "Eritrea":ll(39.78,15.18),"Djibouti":ll(42.59,11.83),"Burundi":ll(29.92,-3.37),
    "Rwanda":ll(29.87,-1.94),"Lesotho":ll(28.23,-29.61),"Eswatini":ll(31.47,-26.52),
    "Comoros":ll(43.87,-11.88),"Cape Verde":ll(-23.61,16.00),"Sao Tome":ll(6.61,0.42),
    "Seychelles":ll(55.49,-4.68),"Vanuatu":ll(167.00,-15.38),"Samoa":ll(-172.10,-13.76),
    "Tonga":ll(-175.20,-21.18),"Kiribati":ll(173.00,1.33),"Palau":ll(134.58,7.52),
    "Nauru":ll(166.93,-0.53),"Tuvalu":ll(177.15,-7.11),"Marshall Islands":ll(168.73,9.15),
    "Micronesia":ll(158.24,6.88),
}
COUNTRY_POOLS = {"EASY":COUNTRIES_EASY,"MEDIUM":COUNTRIES_MEDIUM,"HARD":COUNTRIES_HARD}

# ─────────────────────────────────────────────
# 8.  LEADERBOARD
# ─────────────────────────────────────────────
# Scores are saved to a JSON file in the user's home directory (~/).
# The file structure is: { "EASY": [...], "MEDIUM": [...], "HARD": [...] }
# Each entry is { "name": "ALEX", "score": 1200 }
LEADERBOARD_FILE = os.path.join(os.path.expanduser("~"), "leaderboard.json")

def load_scores(difficulty="MEDIUM"):
    # Read and return the top scores for a given difficulty, sorted highest first.
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE,"r") as f:
                data = json.load(f)
                entries = data.get(difficulty,[]) if isinstance(data,dict) else data
                return sorted(entries, key=lambda x:x["score"], reverse=True)
        except: return []
    return []

def save_score(name, score, difficulty="MEDIUM"):
    # Add a new score to the leaderboard JSON, keeping only the top 10.
    all_data = {}
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE,"r") as f:
                raw = json.load(f)
                if isinstance(raw,dict): all_data = raw
        except: pass
    entries = all_data.get(difficulty,[])
    entries.append({"name":name,"score":score})
    entries = sorted(entries,key=lambda x:x["score"],reverse=True)[:10]
    all_data[difficulty] = entries
    with open(LEADERBOARD_FILE,"w") as f: json.dump(all_data,f)

# ─────────────────────────────────────────────
# 9.  STARFIELD
# ─────────────────────────────────────────────
class StarField:
    def __init__(self):
        # Create three layers of stars at different sizes and speeds to give
        # a parallax (depth) effect: small slow stars feel far away,
        # large fast stars feel close.
        self.stars = []
        for count, radius, speed in [(80,1,0.2),(45,2,0.35),(20,3,0.55)]:
            for _ in range(count):
                self.stars.append({
                    "x":random.randint(0,V_WIDTH),
                    "y":random.randint(0,V_HEIGHT),
                    "r":radius, "speed":speed
                })

    def update_and_draw(self, surface):
        for s in self.stars:
            s["y"] += s["speed"]   # Move star downward each frame
            if s["y"] > V_HEIGHT:  # Wrap back to the top when it exits the screen
                s["y"] = 0; s["x"] = random.randint(0,V_WIDTH)
            # Bigger stars are brighter (higher base brightness value b)
            b = 70 + s["r"]*25
            pygame.draw.circle(surface,(b,b+8,b+18),(int(s["x"]),int(s["y"])),s["r"])

# ─────────────────────────────────────────────
# 10. SCREEN SHAKE
# ─────────────────────────────────────────────
class ScreenShake:
    def __init__(self): self.intensity = 0.0

    def trigger(self, strength=12.0):
        # Start a shake by setting the intensity. Higher = more violent.
        self.intensity = strength

    def get_offset(self):
        # Each frame, return a random (dx, dy) offset to shift the screen.
        # Intensity decays by 12% per frame (multiplied by 0.88) until it
        # drops below 0.5, at which point we stop shaking.
        if self.intensity < 0.5: self.intensity=0.0; return 0,0
        dx,dy = random.uniform(-self.intensity,self.intensity), random.uniform(-self.intensity,self.intensity)
        self.intensity *= 0.88
        return int(dx),int(dy)

# ─────────────────────────────────────────────
# 11. ASTEROID
# ─────────────────────────────────────────────
class Asteroid:
    def __init__(self, target_pos, speed=0.08):
        # Spawn at a random x position just above the top of the screen (-60),
        # then fly toward the target (where the player clicked on the map).
        self.pos=[random.randint(0,V_WIDTH),-60]
        self.target_pos=list(target_pos)
        self.speed=speed; self.active=True; self.landed=False
        self.trail=[]; self._whooshed=False

    def update(self):
        if not self.active: return
        if not self._whooshed: play("whoosh",0.5); self._whooshed=True
        # Record current position in the trail before moving.
        self.trail.append((int(self.pos[0]),int(self.pos[1])))
        if len(self.trail)>16: self.trail.pop(0)   # Keep only the last 16 positions
        # Move toward target using linear interpolation (lerp).
        # Each frame we close self.speed fraction of the remaining distance.
        self.pos[0]+=(self.target_pos[0]-self.pos[0])*self.speed
        self.pos[1]+=(self.target_pos[1]-self.pos[1])*self.speed
        if math.dist(self.pos,self.target_pos)<5:
            self.pos=list(self.target_pos); self.landed=True; self.active=False

    def draw(self, surface):
        if self.active:
            # Draw the glowing trail: each old point is slightly smaller and
            # dimmer than the current position (orange→dark red fade).
            n=max(len(self.trail),1)
            for i,pt in enumerate(self.trail):
                r=max(1,int(3*i/n))
                pygame.draw.circle(surface,(255,max(0,110-i*6),max(0,40-i*3)),pt,r)
            # Draw the asteroid rock itself as a tan circle with a dark outline.
            cx,cy=int(self.pos[0]),int(self.pos[1])
            pygame.draw.circle(surface,(210,185,140),(cx,cy),S(8))
            pygame.draw.circle(surface,(140,120,90),(cx,cy),S(8),2)
        else:
            # After landing, show a red impact ring and small orange dot.
            cx,cy=int(self.target_pos[0]),int(self.target_pos[1])
            pygame.draw.circle(surface,(255,60,30),(cx,cy),S(11),3)
            pygame.draw.circle(surface,(255,180,30),(cx,cy),S(5))

# ─────────────────────────────────────────────
# 12. UI HELPERS
# ─────────────────────────────────────────────
def draw_panel(surface, rect, alpha=220, border_color=C_ACCENT, radius=16):
    # Draw a semi-transparent rounded panel (dark background + colored border).
    # Uses SRCALPHA so the alpha value actually makes it see-through.
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, (*C_PANEL, alpha), (0,0,rect.width,rect.height), border_radius=radius)
    surface.blit(s, rect.topleft)
    pygame.draw.rect(surface, border_color, rect, width=2, border_radius=radius)

def draw_btn(surface, rect, label, font, hover=False, color=C_ACCENT):
    # Draw a button that highlights when hovered. The background becomes
    # brighter blue when the mouse is over it.
    bg = (50,70,110,255) if hover else (*C_BTN, 230)
    s  = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, bg, (0,0,rect.width,rect.height), border_radius=S(10))
    surface.blit(s, rect.topleft)
    pygame.draw.rect(surface, color, rect, width=2, border_radius=S(10))
    t = font.render(label, True, C_WHITE)
    surface.blit(t, t.get_rect(center=rect.center))

def draw_heart(surface, cx, cy, size, color):
    # Draw a heart shape using the parametric heart curve equations.
    # We compute 360 points (one per degree) and connect them as a polygon.
    pts = []
    for i in range(360):
        a = math.radians(i)
        x = size * (16*math.sin(a)**3) / 16
        y = -size * (13*math.cos(a)-5*math.cos(2*a)-2*math.cos(3*a)-math.cos(4*a)) / 16
        pts.append((int(cx+x), int(cy+y)))
    if len(pts) > 2:
        pygame.draw.polygon(surface, color, pts)

# ─────────────────────────────────────────────
# 13. SPLASH SCREEN RENDERER
# ─────────────────────────────────────────────
def draw_splash(surface, star_field, fonts, t_elapsed, fade_alpha):
    # Draw the animated title screen.
    # t_elapsed: seconds since the splash started (used for animations)
    # fade_alpha: 0–255, controls how opaque the content is (fade-in effect)
    title_font, sub_font, tiny_font = fonts
    star_field.update_and_draw(surface)

    # Pulsing ring behind the title — radius and opacity oscillate with sin().
    ring_surf = pygame.Surface((V_WIDTH, V_HEIGHT), pygame.SRCALPHA)
    pulse = 0.5 + 0.5 * math.sin(t_elapsed * 2.0)
    ring_r = int(S(220) + S(20) * pulse)
    ring_alpha = int(30 + 20 * pulse)
    pygame.draw.circle(ring_surf, (*C_ACCENT, ring_alpha),
                       (V_WIDTH // 2, V_HEIGHT // 2), ring_r, S(3))
    pygame.draw.circle(ring_surf, (*C_ACCENT, ring_alpha // 2),
                       (V_WIDTH // 2, V_HEIGHT // 2), ring_r + S(18), S(1))
    surface.blit(ring_surf, (0, 0))

    # Draw title and credits onto a separate surface so we can fade the
    # whole thing in by setting its alpha.
    content = pygame.Surface((V_WIDTH, V_HEIGHT), pygame.SRCALPHA)
    t1 = title_font.render("PLATE", True, C_WHITE)
    t2 = title_font.render("DETECTIVE", True, C_ACCENT)
    cy = V_HEIGHT // 2 - S(90)
    content.blit(t1, t1.get_rect(centerx=V_WIDTH // 2, centery=cy))
    content.blit(t2, t2.get_rect(centerx=V_WIDTH // 2, centery=cy + S(80)))

    # Horizontal divider line below the title
    lw = S(340)
    lx = V_WIDTH // 2 - lw // 2
    ly = cy + S(145)
    pygame.draw.line(content, (*C_ACCENT, 180), (lx, ly), (lx + lw, ly), S(2))

    credit1 = sub_font.render("Created by  Alexander Tran", True, C_GOLD)
    content.blit(credit1, credit1.get_rect(centerx=V_WIDTH // 2, centery=ly + S(40)))
    tagline = tiny_font.render("Identify licence plates from around the world", True, C_DIM)
    content.blit(tagline, tagline.get_rect(centerx=V_WIDTH // 2, centery=ly + S(82)))

    # Blinking "press any key" prompt — only appears after 1.5 seconds.
    # sin() makes the alpha oscillate between ~1 and ~255 for a blink effect.
    if t_elapsed > 1.5:
        blink_alpha = int(128 + 127 * math.sin(t_elapsed * 3.5))
        prompt = sub_font.render("PRESS ANY KEY  OR  CLICK  TO  START", True, C_WHITE)
        prompt_surf = pygame.Surface(prompt.get_size(), pygame.SRCALPHA)
        prompt_surf.blit(prompt, (0, 0))
        prompt_surf.set_alpha(blink_alpha)
        content.blit(prompt_surf, prompt_surf.get_rect(centerx=V_WIDTH // 2,
                                                        centery=V_HEIGHT - S(80)))
    content.set_alpha(fade_alpha)
    surface.blit(content, (0, 0))
    return False


# ─────────────────────────────────────────────
# 14. MAIN GAME LOOP
# ─────────────────────────────────────────────
def main():
    global selected_difficulty
    clock = pygame.time.Clock()

    # ── Font setup ──
    # FS is just an alias for S() here — both scale pixel values to the screen.
    FS = lambda v: S(v)
    title_font  = pygame.font.SysFont("Verdana", FS(64), bold=True)   # Large title text
    head_font   = pygame.font.SysFont("Verdana", FS(30), bold=True)   # Section headings
    ui_font     = pygame.font.SysFont("Verdana", FS(22))              # General UI text
    btn_font    = pygame.font.SysFont("Verdana", FS(26), bold=True)   # Button labels
    small_font  = pygame.font.SysFont("Verdana", FS(17))              # Small labels/hints
    plate_font  = pygame.font.SysFont("Courier New", FS(44), bold=True) # Plate numbers (monospace)
    timer_font  = pygame.font.SysFont("Verdana", FS(28), bold=True)   # Countdown timer
    tiny_font   = pygame.font.SysFont("Verdana", FS(15))              # Very small hints

    # ── Load the world map image ──
    # resource_path() finds the file whether running as .py or as a packed .exe.
    # If the file is missing, fall back to a blank surface so the game doesn't crash.
    map_path = resource_path("world_map.png")
    world_map_base = (
        pygame.image.load(map_path).convert_alpha()
        if os.path.exists(map_path)
        else pygame.Surface((800,450))
    )

    star_field = StarField()
    shaker     = ScreenShake()

    # ── Game state machine ──
    # The game is always in exactly one "state". Each state controls what is
    # drawn and which inputs are accepted. States are simple strings.
    STATE_SPLASH = "splash"   # Animated title screen
    STATE_MENU   = "menu"     # Main menu (Play, How to Play, etc.)
    STATE_GAME   = "game"     # Active gameplay
    STATE_PAUSE  = "pause"    # Paused (overlaid on the game)
    STATE_INST   = "inst"     # "How to Play" instructions screen
    STATE_LEAD   = "lead"     # Leaderboard screen
    STATE_INPUT  = "input"    # Name entry screen after game over
    STATE_DIFF   = "diff"     # Difficulty selection screen

    current_state  = STATE_SPLASH
    splash_t       = 0.0    # Seconds elapsed since splash started
    splash_alpha   = 0      # Opacity of splash content (0=invisible, 255=solid)

    # ── Game variables ──
    target_country = random.choice(list(COUNTRY_POOLS[selected_difficulty].keys()))
    asteroids      = []      # List of active Asteroid objects
    feedback       = ""      # Text shown to player after a guess ("WARM", "CORRECT!", etc.)
    attempts       = DIFFICULTY[selected_difficulty]["attempts"]  # Remaining lives
    game_over      = False
    player_name    = ""      # Name being typed in the input screen
    total_score    = 0
    rounds_cleared = 0
    lb_tab         = "MEDIUM"  # Which difficulty tab is shown on leaderboard
    time_left      = float(DIFFICULTY[selected_difficulty]["time"])
    timer_running  = False
    inst_scroll    = 0       # Scroll offset (pixels) for the instructions screen
    time_up_played = False   # Prevents the time-up sound from repeating

    # ── Map size constants ──
    # The map has two sizes: small (default) and big (when hovered).
    # map_w/map_h smoothly interpolate between them for a zoom animation.
    MAP_SMALL_W = int(V_WIDTH  * 0.44)
    MAP_SMALL_H = int(MAP_SMALL_W * 0.5)
    MAP_BIG_W   = int(V_WIDTH  * 0.62)
    MAP_BIG_H   = int(MAP_BIG_W * 0.5)

    map_w = float(MAP_SMALL_W); map_h = float(MAP_SMALL_H)

    # ── Button rects ──
    # These are updated each frame during drawing so click detection is always
    # accurate to the current frame's layout. Initialized to a 1x1 dummy rect.
    dummy = pygame.Rect(0,0,1,1)
    play_rect=inst_rect=lead_rect=diff_rect=back_rect=dummy
    easy_rect=med_rect=hard_rect=dummy
    resume_rect=restart_rect=quit_to_menu_rect=dummy
    lead_tab_rects = {}

    def map_rect():
        # Compute the map's pygame.Rect based on current map_w/map_h.
        # The map is pinned to the bottom-right corner with a small margin.
        return pygame.Rect(V_WIDTH-int(map_w)-S(20), V_HEIGHT-int(map_h)-S(20),
                           int(map_w), int(map_h))

    def start_new_round():
        # Pick a new random target country and reset the timer for the next round.
        nonlocal target_country,asteroids,feedback,rounds_cleared,time_left,timer_running,time_up_played
        pool = COUNTRY_POOLS[selected_difficulty]
        target_country = random.choice(list(pool.keys()))
        asteroids=[]; feedback=f"CORRECT!  ROUND {rounds_cleared+1}"
        time_left=float(DIFFICULTY[selected_difficulty]["time"]); timer_running=True; time_up_played=False

    def full_reset():
        # Reset ALL game state back to zero for a fresh game.
        nonlocal total_score,rounds_cleared,attempts,game_over,player_name,feedback
        nonlocal asteroids,map_w,map_h,time_left,timer_running,time_up_played,target_country
        d=DIFFICULTY[selected_difficulty]
        total_score=0; rounds_cleared=0; attempts=d["attempts"]; game_over=False
        player_name=""; feedback="FIND THE PLATE ORIGIN"; asteroids=[]
        map_w=float(MAP_SMALL_W); map_h=float(MAP_SMALL_H)
        time_left=float(d["time"]); timer_running=True; time_up_played=False
        target_country=random.choice(list(COUNTRY_POOLS[selected_difficulty].keys()))
        start_new_round()

    # ════════════════════════════════════════
    # MAIN LOOP — runs at 60 fps
    # Each iteration: update state → handle events → draw → flip display
    # ════════════════════════════════════════
    while True:
        dt    = clock.tick(60)/1000.0   # dt = seconds since last frame (~0.0167 at 60fps)
        mpos  = pygame.mouse.get_pos()
        ox,oy = shaker.get_offset()     # Screen shake offset (pixels)
        mr    = map_rect()

        # ── Timer countdown (only during active gameplay) ──
        if current_state==STATE_GAME and timer_running and not game_over:
            time_left -= dt
            if time_left<=0:
                time_left=0; game_over=True; timer_running=False
                feedback=f"TIME'S UP!  It was {target_country.upper()}"
                if not time_up_played: play("time_up",0.8); time_up_played=True

        # ── Splash fade-in ──
        if current_state == STATE_SPLASH:
            splash_t += dt
            splash_alpha = min(255, int(splash_t * 320))  # Reach full opacity in ~0.8s

        # ── Clear screen each frame ──
        screen.fill(C_BG)
        star_field.update_and_draw(screen)

        # ── Event handling ──
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); return

            if event.type == pygame.KEYDOWN:
                if current_state == STATE_SPLASH:
                    if splash_t > 0.4:   # Ignore keypresses during the very first 0.4s
                        current_state = STATE_MENU
                    continue

                # ESC: context-sensitive back/pause/quit
                if event.key == pygame.K_ESCAPE:
                    if current_state == STATE_GAME:
                        current_state = STATE_PAUSE
                        timer_running = False
                    elif current_state == STATE_PAUSE:
                        current_state = STATE_GAME
                        timer_running = not game_over
                    elif current_state in (STATE_INST, STATE_LEAD, STATE_DIFF):
                        current_state = STATE_MENU
                    else:
                        pygame.quit(); return

                # P key: toggle pause during gameplay
                if event.key == pygame.K_p and current_state == STATE_GAME and not game_over:
                    current_state = STATE_PAUSE
                    timer_running = False
                elif event.key == pygame.K_p and current_state == STATE_PAUSE:
                    current_state = STATE_GAME
                    timer_running = not game_over

                # Name input: handle typing, backspace, and enter
                if current_state==STATE_INPUT:
                    if event.key==pygame.K_RETURN and player_name.strip():
                        save_score(player_name,total_score,selected_difficulty)
                        full_reset(); current_state=STATE_LEAD
                    elif event.key==pygame.K_BACKSPACE: player_name=player_name[:-1]
                    elif len(player_name)<12 and event.unicode.isalnum(): player_name+=event.unicode

            # Mouse wheel: scroll the instructions page
            if event.type==pygame.MOUSEWHEEL and current_state==STATE_INST:
                inst_scroll=max(0,inst_scroll-event.y*S(22))

            if event.type==pygame.MOUSEBUTTONDOWN:
                if current_state == STATE_SPLASH:
                    if splash_t > 0.4:
                        current_state = STATE_MENU
                    continue

                # Main menu button clicks
                if current_state==STATE_MENU:
                    if play_rect.collidepoint(mpos): full_reset(); current_state=STATE_GAME
                    elif inst_rect.collidepoint(mpos): inst_scroll=0; current_state=STATE_INST
                    elif lead_rect.collidepoint(mpos): current_state=STATE_LEAD
                    elif diff_rect.collidepoint(mpos): current_state=STATE_DIFF

                # Pause menu button clicks
                elif current_state==STATE_PAUSE:
                    if resume_rect.collidepoint(mpos):
                        current_state=STATE_GAME; timer_running=not game_over
                    elif restart_rect.collidepoint(mpos):
                        full_reset(); current_state=STATE_GAME
                    elif quit_to_menu_rect.collidepoint(mpos):
                        current_state=STATE_MENU

                # Difficulty selection clicks
                elif current_state==STATE_DIFF:
                    if easy_rect.collidepoint(mpos): selected_difficulty="EASY"; current_state=STATE_MENU
                    elif med_rect.collidepoint(mpos): selected_difficulty="MEDIUM"; current_state=STATE_MENU
                    elif hard_rect.collidepoint(mpos): selected_difficulty="HARD"; current_state=STATE_MENU
                    elif back_rect.collidepoint(mpos): current_state=STATE_MENU

                # Back button on instructions/leaderboard, and leaderboard tab switching
                elif current_state in (STATE_INST,STATE_LEAD):
                    if back_rect.collidepoint(mpos): current_state=STATE_MENU
                    if current_state==STATE_LEAD:
                        for k,r in lead_tab_rects.items():
                            if r.collidepoint(mpos): lb_tab=k

                # In-game map clicks: check if the guess is correct
                elif current_state==STATE_GAME:
                    if game_over: current_state=STATE_INPUT
                    elif mr.collidepoint(mpos):
                        d=DIFFICULTY[selected_difficulty]
                        pool=COUNTRY_POOLS[selected_difficulty]
                        # Convert pixel click to (0–1, 0–1) map coordinates
                        rel_x=(mpos[0]-mr.x)/map_w; rel_y=(mpos[1]-mr.y)/map_h
                        tx,ty=pool[target_country]
                        # Euclidean distance between click and target country's position
                        dist=math.sqrt((rel_x-tx)**2+(rel_y-ty)**2)
                        if dist<d["hit_zone"]:
                            # Correct! Award points and start the next round.
                            bonus=int(attempts*100*d["multiplier"])
                            time_bonus=int(bonus*0.5*(time_left/d["time"]))
                            total_score+=bonus+time_bonus; rounds_cleared+=1
                            play("correct",0.9); shaker.trigger(S(14)); start_new_round()
                        else:
                            # Wrong guess: lose a life, spawn asteroid, give distance hint.
                            attempts-=1; play("wrong",0.75)
                            if   dist>0.30: feedback="ICE COLD ❄"
                            elif dist>0.18: feedback="COLD"
                            elif dist>0.10: feedback="WARM"
                            else:           feedback="HOT — SO CLOSE!"
                            asteroids.append(Asteroid(mpos,speed=d["speed"])); shaker.trigger(S(6))
                            if attempts<=0:
                                game_over=True; timer_running=False
                                feedback=f"OUT OF LIVES — It was {target_country.upper()}"
                                play("time_up",0.8)

        # ════════════════════════════════════════
        # DRAWING — one block per state
        # ════════════════════════════════════════

        if current_state == STATE_SPLASH:
            draw_splash(screen, star_field, (title_font, ui_font, tiny_font),
                        splash_t, splash_alpha)

        elif current_state==STATE_MENU:
            d=DIFFICULTY[selected_difficulty]
            t=title_font.render("PLATE DETECTIVE",True,C_WHITE)
            screen.blit(t,t.get_rect(centerx=V_WIDTH//2,y=S(80)))
            sub=ui_font.render("Identify where in the world the licence plate is from",True,C_DIM)
            screen.blit(sub,sub.get_rect(centerx=V_WIDTH//2,y=S(158)))
            mode_s=head_font.render(f"MODE: {selected_difficulty}  ·  {d['time']}s per round",True,d["color"])
            screen.blit(mode_s,mode_s.get_rect(centerx=V_WIDTH//2,y=S(200)))
            bw,bh=S(300),S(60)
            bx=V_WIDTH//2-bw//2
            # Define button rects here each frame so click detection stays accurate
            play_rect=pygame.Rect(bx,S(275),bw,bh)
            inst_rect=pygame.Rect(bx,S(355),bw,bh)
            diff_rect=pygame.Rect(bx,S(435),bw,bh)
            lead_rect=pygame.Rect(bx,S(515),bw,bh)
            for rect,label in [(play_rect,"▶  PLAY"),(inst_rect,"HOW TO PLAY"),(diff_rect,"DIFFICULTY"),(lead_rect,"SCORES")]:
                draw_btn(screen,rect,label,btn_font,hover=rect.collidepoint(mpos),color=d["color"] if label=="▶  PLAY" else C_ACCENT)
            esc=tiny_font.render("ESC to quit",True,C_DIM)
            screen.blit(esc,esc.get_rect(centerx=V_WIDTH//2,y=V_HEIGHT-S(30)))

        elif current_state==STATE_INST:
            # ── Scrollable instructions panel ──
            pw,ph=S(800),V_HEIGHT-S(100)
            panel=pygame.Rect(V_WIDTH//2-pw//2,S(50),pw,ph)
            draw_panel(screen,panel)
            screen.blit(head_font.render("HOW TO PLAY",True,C_GOLD),
                        head_font.render("HOW TO PLAY",True,C_GOLD).get_rect(centerx=V_WIDTH//2,y=panel.y+S(16)))
            sections=[
                ("OBJECTIVE",C_ACCENT,""),
                ("",C_WHITE,"A mystery licence plate appears on screen. Click the correct country on the world map."),
                None,
                ("PLATES",C_ACCENT,""),
                ("",C_WHITE,"Each plate is styled to match its real country — EU blue strips, Chinese characters, Arabic text, etc."),
                None,
                ("THE MAP",C_ACCENT,""),
                ("",C_WHITE,"Shown in the bottom-right corner. Hover over it to zoom in for precision clicking."),
                ("",C_WHITE,"All country positions use accurate geographic coordinates."),
                None,
                ("FEEDBACK",C_ACCENT,""),
                ("  ICE COLD ❄",C_WHITE,"Very far away."),
                ("  COLD",C_WHITE,"Getting closer."),
                ("  WARM",C_WHITE,"You're in the right region."),
                ("  HOT",C_WHITE,"Almost there — just missed!"),
                None,
                ("DIFFICULTY",C_ACCENT,""),
                ("  Easy",C_GREEN,"15 iconic countries · 7 lives · 45 sec · x1 score"),
                ("  Medium",C_GOLD,"35+ countries · 5 lives · 30 sec · x2 score"),
                ("  Hard",C_RED,"50+ countries · 3 lives · 20 sec · x4 score"),
                None,
                ("SCORING",C_ACCENT,""),
                ("",C_WHITE,"Lives × 100 × Multiplier, plus a time bonus of up to 50%."),
                None,
                ("CONTROLS",C_ACCENT,""),
                ("",C_WHITE,"Click the map to guess. ESC or P to pause mid-game. ESC from menu to quit."),
            ]
            lh=S(28); content_h=sum(lh if s is not None else S(12) for s in sections)+S(20)
            # Render all text onto an off-screen surface, then scroll it by
            # blitting only the visible portion using set_clip().
            content=pygame.Surface((pw-S(40),content_h),pygame.SRCALPHA)
            cy2=0
            for item in sections:
                if item is None: cy2+=S(12); continue
                lbl,col,det=item
                if lbl: content.blit(small_font.render(lbl,True,col),(S(10),cy2))
                if det: content.blit(small_font.render(det,True,(185,200,225)),(S(200) if lbl else S(20),cy2))
                cy2+=lh
            max_scroll=max(0,content_h-(ph-S(100)))
            inst_scroll=min(inst_scroll,max_scroll)
            clip=pygame.Rect(panel.x+S(20),panel.y+S(58),pw-S(40),ph-S(100))
            screen.set_clip(clip)
            screen.blit(content,(panel.x+S(20),panel.y+S(58)-inst_scroll))
            screen.set_clip(None)
            if max_scroll>0:
                # Draw a proportional scrollbar on the right edge
                sb_h=int((ph-S(100))**2/content_h)
                sb_y=panel.y+S(58)+int((ph-S(100)-sb_h)*inst_scroll/max(max_scroll,1))
                pygame.draw.rect(screen,(80,100,140),pygame.Rect(panel.right-S(10),sb_y,S(6),sb_h),border_radius=3)
                hi=tiny_font.render("scroll ↓",True,C_DIM); screen.blit(hi,(panel.right-hi.get_width()-S(16),panel.bottom-S(36)))
            back_rect=pygame.Rect(V_WIDTH//2-S(100),panel.bottom-S(52),S(200),S(42))
            draw_btn(screen,back_rect,"← BACK",btn_font,hover=back_rect.collidepoint(mpos))

        elif current_state==STATE_DIFF:
            pw,ph=S(720),S(520)
            panel=pygame.Rect(V_WIDTH//2-pw//2,V_HEIGHT//2-ph//2,pw,ph)
            draw_panel(screen,panel)
            screen.blit(head_font.render("SELECT DIFFICULTY",True,C_GOLD),
                        head_font.render("SELECT DIFFICULTY",True,C_GOLD).get_rect(centerx=V_WIDTH//2,y=panel.y+S(18)))
            rw,rh=pw-S(80),S(95)
            easy_rect=pygame.Rect(panel.x+S(40),panel.y+S(80),rw,rh)
            med_rect=pygame.Rect(panel.x+S(40),panel.y+S(195),rw,rh)
            hard_rect=pygame.Rect(panel.x+S(40),panel.y+S(310),rw,rh)
            rows=[("EASY",easy_rect,"7 lives · Large hit zone · Slow asteroids · x1 score","15 iconic countries · 45 sec/round"),
                  ("MEDIUM",med_rect,"5 lives · Normal hit zone · x2 score","35+ countries including lesser-known nations · 30 sec/round"),
                  ("HARD",hard_rect,"3 lives · Tiny hit zone · Rapid asteroids · x4 score","50+ obscure countries worldwide · 20 sec/round")]
            for key,rect,l1,l2 in rows:
                col=DIFFICULTY[key]["color"]; sel=(key==selected_difficulty)
                # Highlight the currently selected difficulty with a tinted background
                bg=(*col[:3],50) if sel else (*C_BTN,210)
                s=pygame.Surface(rect.size,pygame.SRCALPHA); pygame.draw.rect(s,bg,(0,0,rect.width,rect.height),border_radius=S(12)); screen.blit(s,rect.topleft)
                pygame.draw.rect(screen,col if sel else C_DIM,rect,width=2,border_radius=S(12))
                screen.blit(btn_font.render(key,True,col),(rect.x+S(18),rect.y+S(10)))
                screen.blit(tiny_font.render(l1,True,(185,200,225)),(rect.x+S(18),rect.y+S(46)))
                screen.blit(tiny_font.render(l2,True,col),(rect.x+S(18),rect.y+S(68)))
                if sel:
                    chk=tiny_font.render("✓ SELECTED",True,col); screen.blit(chk,(rect.right-chk.get_width()-S(16),rect.y+S(10)))
            back_rect=pygame.Rect(V_WIDTH//2-S(100),panel.bottom-S(60),S(200),S(42))
            draw_btn(screen,back_rect,"← BACK",btn_font,hover=back_rect.collidepoint(mpos))

        elif current_state==STATE_LEAD:
            pw,ph=S(620),S(600)
            panel=pygame.Rect(V_WIDTH//2-pw//2,V_HEIGHT//2-ph//2,pw,ph)
            draw_panel(screen,panel)
            screen.blit(head_font.render("TOP AGENTS",True,C_GOLD),
                        head_font.render("TOP AGENTS",True,C_GOLD).get_rect(centerx=V_WIDTH//2,y=panel.y+S(18)))
            # Three tabs at the top to switch between Easy/Medium/Hard scoreboards
            tw=S(150)
            lead_tab_rects={
                "EASY":  pygame.Rect(panel.x+S(30),panel.y+S(62),tw,S(34)),
                "MEDIUM":pygame.Rect(panel.x+S(30)+tw+S(10),panel.y+S(62),tw,S(34)),
                "HARD":  pygame.Rect(panel.x+S(30)+(tw+S(10))*2,panel.y+S(62),tw,S(34)),
            }
            for k,r in lead_tab_rects.items():
                col=DIFFICULTY[k]["color"]; active=(k==lb_tab)
                bg=(*col[:3],70) if active else (*C_BTN,200)
                s=pygame.Surface(r.size,pygame.SRCALPHA); pygame.draw.rect(s,bg,(0,0,r.width,r.height),border_radius=S(8)); screen.blit(s,r.topleft)
                pygame.draw.rect(screen,col if active else C_DIM,r,width=2,border_radius=S(8))
                lbl=small_font.render(k,True,col if active else C_DIM); screen.blit(lbl,lbl.get_rect(center=r.center))
            scores=load_scores(lb_tab)
            # Show up to 8 entries; top 3 get medal colors (gold, silver-ish, silver-ish)
            for i,entry in enumerate(scores[:8]):
                medal=["1.","2.","3."][i] if i<3 else f"{i+1}."
                ry=panel.y+S(112)+i*S(52)
                col=C_GOLD if i==0 else (210,210,225) if i<3 else C_WHITE
                screen.blit(ui_font.render(f"{medal}  {entry['name']}",True,col),(panel.x+S(40),ry))
                sc=ui_font.render(str(entry["score"]),True,col); screen.blit(sc,(panel.right-sc.get_width()-S(40),ry))
                pygame.draw.line(screen,C_DIM,(panel.x+S(30),ry+S(44)),(panel.right-S(30),ry+S(44)),1)
            if not scores:
                ns=ui_font.render("No scores yet!",True,C_DIM); screen.blit(ns,ns.get_rect(centerx=V_WIDTH//2,y=panel.y+S(250)))
            back_rect=pygame.Rect(V_WIDTH//2-S(100),panel.bottom-S(56),S(200),S(42))
            draw_btn(screen,back_rect,"← BACK",btn_font,hover=back_rect.collidepoint(mpos))

        elif current_state==STATE_INPUT:
            # ── Name entry screen shown after game over ──
            pw,ph=S(560),S(340)
            panel=pygame.Rect(V_WIDTH//2-pw//2,V_HEIGHT//2-ph//2,pw,ph)
            draw_panel(screen,panel,border_color=C_GOLD)
            screen.blit(head_font.render("GAME OVER",True,C_RED),
                        head_font.render("GAME OVER",True,C_RED).get_rect(centerx=V_WIDTH//2,y=panel.y+S(18)))
            st2=ui_font.render(f"Score: {total_score}   ·   Rounds: {rounds_cleared}",True,C_GOLD)
            screen.blit(st2,st2.get_rect(centerx=V_WIDTH//2,y=panel.y+S(72)))
            screen.blit(ui_font.render("Enter Agent Name:",True,C_WHITE),(panel.x+S(60),panel.y+S(120)))
            # Input box: dark background + gold border, shows typed name + blinking cursor "_"
            ib=pygame.Rect(panel.x+S(60),panel.y+S(158),pw-S(120),S(54))
            pygame.draw.rect(screen,(12,18,38),ib,border_radius=S(8))
            pygame.draw.rect(screen,C_GOLD,ib,2,border_radius=S(8))
            screen.blit(btn_font.render(player_name+"_",True,C_GOLD),(ib.x+S(14),ib.y+S(12)))
            hi=tiny_font.render("Press ENTER to confirm",True,C_DIM); screen.blit(hi,hi.get_rect(centerx=V_WIDTH//2,y=panel.y+S(238)))

        elif current_state in (STATE_GAME, STATE_PAUSE):
            d=DIFFICULTY[selected_difficulty]

            # ── Animate map zoom on hover ──
            # Each frame we move map_w/map_h 14% closer to the target size.
            # This creates a smooth exponential ease-in/ease-out zoom.
            hover=mr.collidepoint(mpos) and current_state==STATE_GAME
            target_mw=float(MAP_BIG_W) if hover else float(MAP_SMALL_W)
            target_mh=float(MAP_BIG_H) if hover else float(MAP_SMALL_H)
            map_w+=(target_mw-map_w)*0.14
            map_h+=(target_mh-map_h)*0.14
            mr=map_rect()

            # ── Update asteroids (only when not paused) ──
            if current_state==STATE_GAME:
                for a in asteroids:
                    a.update()
                    if a.landed: play("impact",0.7); shaker.trigger(S(8)); a.landed=False
                # Remove asteroids that have finished their animation
                asteroids=[a for a in asteroids if not (not a.active and not a.landed)]

            # ── Draw the world map (scaled to current animated size) ──
            curr_map=pygame.transform.smoothscale(world_map_base,(int(map_w),int(map_h)))
            screen.blit(curr_map,(mr.x+ox,mr.y+oy))   # ox/oy = screen shake offset
            pygame.draw.rect(screen,C_ACCENT if hover else C_DIM,mr.move(ox,oy),width=3,border_radius=S(14))
            if not hover and current_state==STATE_GAME:
                lbl=tiny_font.render("HOVER TO ZOOM  ·  CLICK TO GUESS",True,C_DIM)
                screen.blit(lbl,lbl.get_rect(centerx=mr.centerx,y=mr.y-S(20)))

            for a in asteroids: a.draw(screen)

            # ── HUD (heads-up display): lives, score, round, mode ──
            hud_h = S(68)
            hs    = pygame.Surface((V_WIDTH,hud_h),pygame.SRCALPHA)
            pygame.draw.rect(hs,(*C_PANEL,245),(0,0,V_WIDTH,hud_h))
            screen.blit(hs,(0,0))
            pygame.draw.line(screen,C_DIM,(0,hud_h),(V_WIDTH,hud_h),1)

            cy_hud = hud_h//2
            lx = S(30)

            # Lives section: heart icons (red = remaining, dark = lost)
            lbl_lives=small_font.render("LIVES",True,C_DIM)
            screen.blit(lbl_lives,(lx,cy_hud-lbl_lives.get_height()//2))
            lx+=lbl_lives.get_width()+S(12)
            max_lives=DIFFICULTY[selected_difficulty]["attempts"]
            for i in range(max_lives):
                col=C_RED if i<attempts else (50,55,80)
                draw_heart(screen,lx+i*S(22),cy_hud,S(8),col)
            lx+=max_lives*S(22)+S(24)
            pygame.draw.line(screen,C_DIM,(lx,S(12)),(lx,hud_h-S(12)),1); lx+=S(18)

            # Score section
            scl=small_font.render("SCORE",True,C_DIM); screen.blit(scl,(lx,cy_hud-S(22)))
            scv=head_font.render(str(total_score),True,C_GOLD); screen.blit(scv,(lx,cy_hud-S(4)))
            lx+=max(scl.get_width(),scv.get_width())+S(24)
            pygame.draw.line(screen,C_DIM,(lx,S(12)),(lx,hud_h-S(12)),1); lx+=S(18)

            # Round counter
            rdl=small_font.render("ROUND",True,C_DIM); screen.blit(rdl,(lx,cy_hud-S(22)))
            rdv=head_font.render(str(rounds_cleared+1),True,C_WHITE); screen.blit(rdv,(lx,cy_hud-S(4)))
            lx+=max(rdl.get_width(),rdv.get_width())+S(24)
            pygame.draw.line(screen,C_DIM,(lx,S(12)),(lx,hud_h-S(12)),1); lx+=S(18)

            # Difficulty label
            mdl=small_font.render("MODE",True,C_DIM); screen.blit(mdl,(lx,cy_hud-S(22)))
            mdv=small_font.render(selected_difficulty,True,d["color"]); screen.blit(mdv,(lx,cy_hud+S(2)))

            ph_lbl=tiny_font.render("P / ESC = Pause",True,C_DIM)
            screen.blit(ph_lbl,(V_WIDTH-ph_lbl.get_width()-S(20),cy_hud-ph_lbl.get_height()//2))

            # ── Timer bar: colored progress bar below the HUD ──
            # Color shifts green → gold → red as time runs out.
            timer_h = S(8)
            frac    = max(0, time_left/d["time"])   # 1.0 = full time, 0.0 = expired
            tcol    = C_GREEN if frac>0.5 else C_GOLD if frac>0.25 else C_RED
            pygame.draw.rect(screen,(20,26,46),(0,hud_h,V_WIDTH,timer_h))           # Background track
            pygame.draw.rect(screen,tcol,(0,hud_h,int(V_WIDTH*frac),timer_h))       # Filled portion
            secs=timer_font.render(f"{math.ceil(time_left)}s",True,tcol)
            screen.blit(secs,(V_WIDTH-secs.get_width()-S(16),hud_h+timer_h+S(4)))

            # ── Plate display area (left side of screen) ──
            left_area_w = mr.x - S(20)        # Available width to the left of the map
            plate_cx    = left_area_w // 2    # Horizontal center of that area
            play_area_top = hud_h + timer_h + S(16)
            play_area_h   = V_HEIGHT - play_area_top
            plate_cy      = play_area_top + play_area_h // 3   # Place plate in upper third

            draw_license_plate(screen, target_country, plate_cx+ox, plate_cy+oy, plate_font, small_font)

            q=small_font.render("Which country is this plate from?",True,C_DIM)
            screen.blit(q,q.get_rect(centerx=plate_cx,y=plate_cy+S(80)))

            # ── Feedback text (CORRECT, COLD, HOT, etc.) ──
            if feedback:
                is_good="CORRECT" in feedback
                is_bad =any(w in feedback for w in ("LIVES","TIME","OUT"))
                fc = C_GREEN if is_good else C_RED if is_bad else C_GOLD
                fs = head_font.render(feedback,True,fc)
                screen.blit(fs,fs.get_rect(centerx=plate_cx,y=plate_cy+S(120)))

            # ── Game over prompt ──
            if game_over and current_state==STATE_GAME:
                ov=head_font.render("▶  CLICK ANYWHERE TO CONTINUE",True,C_WHITE)
                screen.blit(ov,ov.get_rect(centerx=V_WIDTH//2,y=V_HEIGHT-S(50)))

            # ── Pause overlay (drawn on top of the frozen game screen) ──
            if current_state == STATE_PAUSE:
                # Semi-transparent dark overlay to dim the background
                dim = pygame.Surface((V_WIDTH, V_HEIGHT), pygame.SRCALPHA)
                pygame.draw.rect(dim, (0, 0, 0, 165), (0, 0, V_WIDTH, V_HEIGHT))
                screen.blit(dim, (0, 0))

                ppw, pph = S(480), S(400)
                ppanel = pygame.Rect(V_WIDTH//2-ppw//2, V_HEIGHT//2-pph//2, ppw, pph)
                draw_panel(screen, ppanel, alpha=245, border_color=C_ACCENT, radius=S(18))

                pause_title = head_font.render("⏸  PAUSED", True, C_WHITE)
                screen.blit(pause_title, pause_title.get_rect(centerx=V_WIDTH//2, y=ppanel.y+S(22)))

                pygame.draw.line(screen, C_DIM,
                                 (ppanel.x+S(30), ppanel.y+S(74)),
                                 (ppanel.right-S(30), ppanel.y+S(74)), 1)

                stat_txt = small_font.render(
                    f"Score: {total_score}   ·   Round: {rounds_cleared+1}   ·   Lives: {attempts}",
                    True, C_DIM)
                screen.blit(stat_txt, stat_txt.get_rect(centerx=V_WIDTH//2, y=ppanel.y+S(86)))

                bw2, bh2 = ppw-S(80), S(60)
                bx2 = ppanel.x+S(40)
                resume_rect       = pygame.Rect(bx2, ppanel.y+S(130), bw2, bh2)
                restart_rect      = pygame.Rect(bx2, ppanel.y+S(210), bw2, bh2)
                quit_to_menu_rect = pygame.Rect(bx2, ppanel.y+S(290), bw2, bh2)

                draw_btn(screen, resume_rect,      "▶  RESUME",        btn_font,
                         hover=resume_rect.collidepoint(mpos),       color=C_GREEN)
                draw_btn(screen, restart_rect,     "↺  RESTART GAME",  btn_font,
                         hover=restart_rect.collidepoint(mpos),      color=C_GOLD)
                draw_btn(screen, quit_to_menu_rect,"⌂  QUIT TO MENU",  btn_font,
                         hover=quit_to_menu_rect.collidepoint(mpos), color=C_RED)

                hint = tiny_font.render("Press P or ESC to resume", True, C_DIM)
                screen.blit(hint, hint.get_rect(centerx=V_WIDTH//2, y=ppanel.bottom-S(28)))

        # ── Flip the display: show the completed frame ──
        pygame.display.flip()


if __name__=="__main__":
    main()