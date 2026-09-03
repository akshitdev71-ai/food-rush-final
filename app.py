import io
import math
import sqlite3
import uuid
from datetime import datetime, timedelta
import folium
import pandas as pd
import qrcode
import streamlit as st
from streamlit_folium import st_folium

# --- DATABASE SETUP ---
DB_NAME = "foodrush.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drops (
            id TEXT PRIMARY KEY,
            merchant_name TEXT NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            claim_type TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            status TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            drop_id TEXT NOT NULL,
            user_type TEXT NOT NULL,
            claimed_at TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (drop_id) REFERENCES drops (id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- UTILITIES ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def generate_qr(data):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# --- APP CONFIG & NAVIGATION ---
st.set_page_config(page_title="FoodRush | Food Rescue", page_icon="🍲", layout="wide")

st.sidebar.title("🍲 Food Rush Network")
role = st.sidebar.radio("Select Portal View:", ["Buyer / NGO Discovery", "Merchant Drop Console", "Merchant QR Scanner"])

# Default center: Local urban hub coords (Change to your hackathon venue)
VENUE_LAT, VENUE_LON = 28.6139, 77.2090

# --- VIEW 1: MERCHANT CONSOLE ---
if role == "Merchant Drop Console":
    st.header("🏪 Merchant Flash Drop Console")
    st.caption("Publish daily unsold inventory within 45 seconds to local rescue channels.")

    with st.form("new_drop_form"):
        col1, col2 = st.columns(2)
        with col1:
            merchant_name = st.text_input("Store Name", value="Artisan Bakes & Cafe")
            item_name = st.text_input("Surplus Pack Title", placeholder="e.g., Sourdough & Croissant Mystery Bag")
            category = st.selectbox("Category", ["Bakery & Pastry", "Cooked Meals", "Dairy & Deli", "Produce"])
            claim_type = st.radio("Access Rule", ["NGO Priority (Free for 20m, then Discounted)", "Consumer Flash Markdown"])
        with col2:
            price = st.number_input("Discounted Price (₹)", min_value=0.0, value=70.0, step=0.5)
            quantity = st.number_input("Bags Available", min_value=1, value=4, step=1)
            expiry_minutes = st.slider("Window Closes In (Minutes)", 15, 120, 45)
            # Offset coords slightly to simulate real neighborhood businesses
            lat = st.number_input("Latitude", value=VENUE_LAT + 0.003, format="%.6f")
            lon = st.number_input("Longitude", value=VENUE_LON - 0.002, format="%.6f")

        submitted = st.form_submit_button("🚀 Publish Drop")
        if submitted:
            drop_id = str(uuid.uuid4())[:8]
            now = datetime.utcnow()
            expires = now + timedelta(minutes=expiry_minutes)
            
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO drops VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (drop_id, merchant_name, item_name, category, price, quantity, claim_type, lat, lon, now, expires, "ACTIVE")
            )
            conn.commit()
            conn.close()
            st.success(f"Drop '{item_name}' published! Live for {expiry_minutes} mins.")

    st.subheader("Active Store Drops")
    conn = get_db_connection()
    active_drops = pd.read_sql_query("SELECT id, item_name, quantity, price, expires_at, status FROM drops ORDER BY created_at DESC", conn)
    conn.close()
    st.dataframe(active_drops, use_container_width=True)

# --- VIEW 2: BUYER / NGO DISCOVERY ---
elif role == "Buyer / NGO Discovery":
    st.header("📍 Real-Time Food Rescue Radar")

    col_filter1, col_filter2 = st.columns([1, 2])
    with col_filter1:
        user_type = st.selectbox("I am ordering as:", ["Consumer / Student", "Verified NGO / Shelter"])
        max_dist = st.slider("Max Search Radius (km)", 1.0, 15.0, 5.0)

    # Fetch and filter live drops
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drops WHERE status = 'ACTIVE' AND quantity > 0")
    rows = cursor.fetchall()
    conn.close()

    nearby_drops = []
    now = datetime.utcnow()

    for r in rows:
        exp = datetime.fromisoformat(r["expires_at"])
        if exp < now:
            continue
        dist = haversine(VENUE_LAT, VENUE_LON, r["lat"], r["lon"])
        if dist <= max_dist:
            item = dict(r)
            item["distance"] = round(dist, 2)
            nearby_drops.append(item)

    # Folium Interactive Map
    drop_map = folium.Map(location=[VENUE_LAT, VENUE_LON], zoom_start=14)
    folium.Marker(
        [VENUE_LAT, VENUE_LON],
        tooltip="You Are Here",
        icon=folium.Icon(color="blue", icon="user", prefix="fa")
    ).add_to(drop_map)

    for d in nearby_drops:
        popup_text = f"{d['merchant_name']}: {d['item_name']} | Qty: {d['quantity']} | Price: {d['price']}"
        folium.Marker(
            [d["lat"], d["lon"]],
            popup=popup_text,
            tooltip=f"{d['item_name']} ({d['distance']} km)",
            icon=folium.Icon(color="green" if d["price"] == 0 else "orange", icon="cutlery", prefix="fa")
        ).add_to(drop_map)

    with col_filter2:
        st_folium(drop_map, width=700, height=350)

    st.subheader(f"Available Deals Within {max_dist} km")
    if not nearby_drops:
        st.info("No drops available in this perimeter. Try expanding the radius.")
    else:
        for d in nearby_drops:
            card = st.container(border=True)
            c1, c2, c3 = card.columns([3, 1, 1])
            with c1:
                st.write(f"**{d['merchant_name']}** — *{d['item_name']}*")
                st.caption(f"Category: {d['category']} | {d['distance']} km away | Expires at: {d['expires_at'][:16]}")
            with c2:
                price_tag = "FREE (Donation)" if d["price"] == 0 else f"${d['price']:.2f}"
                st.markdown(f"### {price_tag}")
                st.caption(f"{d['quantity']} units left")
            with c3:
                if st.button("Claim Pick-up", key=f"claim_{d['id']}"):
                    claim_id = f"CLM-{uuid.uuid4().hex[:6].upper()}"
                    conn = get_db_connection()
                    conn.execute("UPDATE drops SET quantity = quantity - 1 WHERE id = ?", (d["id"],))
                    conn.execute(
                        "INSERT INTO claims VALUES (?, ?, ?, ?, ?)",
                        (claim_id, d["id"], user_type, datetime.utcnow(), "READY")
                    )
                    conn.commit()
                    conn.close()
                    st.session_state["active_claim"] = {
                        "claim_id": claim_id,
                        "item": d["item_name"],
                        "store": d["merchant_name"]
                    }
                    st.rerun()

    if "active_claim" in st.session_state:
        st.divider()
        st.success("🎉 Claim Confirmed! Present this QR at the counter:")
        c = st.session_state["active_claim"]
        qr_bytes = generate_qr(f"BITEBACK_VERIFY:{c['claim_id']}")
        qcol1, qcol2 = st.columns([1, 3])
        with qcol1:
            st.image(qr_bytes, width=180)
        with qcol2:
            st.write(f"**Token:** `{c['claim_id']}`")
            st.write(f"**Pickup Store:** {c['store']}")
            st.write(f"**Item:** {c['item']}")

# --- VIEW 3: MERCHANT SCANNER / VERIFICATION ---
elif role == "Merchant QR Scanner":
    st.header("📷 Counter Verification & Burn Console")
    st.caption("Verify customer claims upon arrival to clear stock.")

    token_input = st.text_input("Enter Claim Code or Scan Payload", placeholder="e.g., CLM-3A9B2F")

    if st.button("Verify & Complete Handover"):
        token = token_input.replace("BITEBACK_VERIFY:", "").strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM claims WHERE claim_id = ?", (token,))
        claim = cursor.fetchone()

        if not claim:
            st.error("Invalid token. Not recognized in records.")
        elif claim["status"] == "COMPLETED":
            st.warning("This QR code has already been redeemed.")
        else:
            conn.execute("UPDATE claims SET status = 'COMPLETED' WHERE claim_id = ?", (token,))
            conn.commit()
            st.balloons()
            st.success(f"Success! Claim {token} verified and burned. Hand food to customer.")
        conn.close()
