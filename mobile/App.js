/**
 * Signal Bot — Expo Go mobil izleyici.
 *
 * MIMARI / KISIT (bilincli tercih, bkz. mobile/README.md):
 *   Expo Go SDK 53+ uzak (remote) push'u desteklemez. Bu yuzden uygulama,
 *   sunucudaki /signals/latest endpoint'ini UYGULAMA ON PLANDAYKEN her
 *   POLL_SECONDS saniyede bir pollar ve yeni sinyal gelince expo-notifications
 *   ile YEREL (local) bildirim tetikler. Local bildirimler Expo Go'da calisir.
 *   => Uygulama tamamen kapaliyken/arka planda uzun sureyken bildirim GELMEZ.
 *      "Kacirmadan" 7/24 uyari icin Telegram/email kanallari vardir.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, AppState, FlatList, Platform, RefreshControl,
  SafeAreaView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Notifications from "expo-notifications";

const POLL_SECONDS = 45;          // 30-60 sn araligi icinde
const FETCH_LIMIT = 50;
const K_URL = "serverUrl";
const K_LAST = "lastNotifiedAt";

// Bildirim on plandayken de banner olarak gorunsun (SDK 53: banner+list).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,     // eski API uyumu
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

const normalizeUrl = (u) => (u || "").trim().replace(/\/+$/, "");
const sigTime = (s) => s.notified_at || s.bar_time || "";
const sigMs = (s) => {
  const t = Date.parse(sigTime(s));
  return Number.isNaN(t) ? 0 : t;
};
const isStrong = (s) => s.strength === "STRONG";

function detailRows(s) {
  const rows = [];
  if (s.rsi !== undefined) rows.push(["RSI", String(s.rsi)]);
  if (s.volume_logz !== undefined) rows.push(["Hacim log-Z", String(s.volume_logz)]);
  if (s.funding_pct !== undefined)
    rows.push(["Funding %", [].concat(s.funding_pct).join(", ")]);
  return rows;
}

function fmtTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || "";
  return d.toLocaleString();
}

async function ensureNotificationPermission() {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "Sinyaller",
      importance: Notifications.AndroidImportance.HIGH,
    });
  }
  const cur = await Notifications.getPermissionsAsync();
  if (cur.granted || cur.status === "granted") return true;
  const req = await Notifications.requestPermissionsAsync();
  return req.granted || req.status === "granted";
}

async function fireLocalNotification(s) {
  const icon = isStrong(s) ? "‼️" : "🔔";
  const title = `${icon} ${s.strategy} · ${s.symbol} ${s.direction}`;
  const body = `Fiyat ${s.price} · ~${s.horizon_hours}s · ${s.note}`;
  try {
    await Notifications.scheduleNotificationAsync({
      content: { title, body, data: { symbol: s.symbol } },
      trigger: null,               // hemen
    });
  } catch (e) {
    // bildirim hatasi akisi bozmasin
    console.warn("local notification error", e);
  }
}

export default function App() {
  const [screen, setScreen] = useState("signals");
  const [serverUrl, setServerUrl] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const [signals, setSignals] = useState([]);
  const [status, setStatus] = useState("idle");   // idle|loading|ok|error
  const [errorMsg, setErrorMsg] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [notifOk, setNotifOk] = useState(false);

  const lastNotifiedMsRef = useRef(null);          // baseline: null => ilk yukleme
  const pollRef = useRef(null);
  const serverUrlRef = useRef("");

  // ilk acilis: ayarlari + baseline zaman damgasini + bildirim iznini yukle
  useEffect(() => {
    (async () => {
      const [u, last] = await Promise.all([
        AsyncStorage.getItem(K_URL),
        AsyncStorage.getItem(K_LAST),
      ]);
      if (u) { setServerUrl(u); setDraftUrl(u); serverUrlRef.current = u; }
      lastNotifiedMsRef.current = last ? Date.parse(last) : null;
      const ok = await ensureNotificationPermission();
      setNotifOk(ok);
    })();
  }, []);

  const processNewSignals = useCallback(async (list) => {
    // list: sunucudan (yeni->eski). Bildirim icin eskiden yeniye sirala.
    const asc = [...list].sort((a, b) => sigMs(a) - sigMs(b));
    if (lastNotifiedMsRef.current === null) {
      // baseline — ilk yuklemede eski sinyaller icin bildirim YAGDIRMA
      const newest = asc.length ? sigMs(asc[asc.length - 1]) : Date.now();
      lastNotifiedMsRef.current = newest;
      await AsyncStorage.setItem(K_LAST, new Date(newest).toISOString());
      return;
    }
    let hi = lastNotifiedMsRef.current;
    for (const s of asc) {
      const t = sigMs(s);
      if (t > lastNotifiedMsRef.current) {
        await fireLocalNotification(s);
        if (t > hi) hi = t;
      }
    }
    if (hi > lastNotifiedMsRef.current) {
      lastNotifiedMsRef.current = hi;
      await AsyncStorage.setItem(K_LAST, new Date(hi).toISOString());
    }
  }, []);

  const fetchSignals = useCallback(async () => {
    const base = normalizeUrl(serverUrlRef.current);
    if (!base) { setStatus("idle"); return; }
    setStatus((p) => (p === "ok" ? "ok" : "loading"));
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 15000);
      const res = await fetch(`${base}/signals/latest?limit=${FETCH_LIMIT}`,
        { signal: ctrl.signal });
      clearTimeout(to);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const list = Array.isArray(data.signals) ? data.signals : [];
      setSignals(list);
      setStatus("ok");
      setErrorMsg("");
      setLastUpdated(new Date());
      await processNewSignals(list);
    } catch (e) {
      setStatus("error");
      setErrorMsg(e.name === "AbortError" ? "Zaman asimi (sunucu uykuda olabilir)"
        : String(e.message || e));
    }
  }, [processNewSignals]);

  // polling + AppState (arka plana gecince duraklat, one gelince hemen cek)
  useEffect(() => {
    if (!serverUrl) return;
    serverUrlRef.current = serverUrl;
    fetchSignals();
    const startPoll = () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(fetchSignals, POLL_SECONDS * 1000);
    };
    startPoll();
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") { fetchSignals(); startPoll(); }
      else if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    });
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      sub.remove();
    };
  }, [serverUrl, fetchSignals]);

  const saveUrl = async () => {
    const u = normalizeUrl(draftUrl);
    setServerUrl(u);
    serverUrlRef.current = u;
    await AsyncStorage.setItem(K_URL, u);
    setScreen("signals");
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" />
      <View style={styles.header}>
        <Text style={styles.title}>Signal Bot</Text>
        <View style={styles.tabs}>
          <Tab label="Sinyaller" active={screen === "signals"}
            onPress={() => setScreen("signals")} />
          <Tab label="Ayarlar" active={screen === "settings"}
            onPress={() => setScreen("settings")} />
        </View>
      </View>

      {screen === "settings"
        ? <Settings draftUrl={draftUrl} setDraftUrl={setDraftUrl} onSave={saveUrl}
            notifOk={notifOk} serverUrl={serverUrl} />
        : <Signals signals={signals} status={status} errorMsg={errorMsg}
            serverUrl={serverUrl} lastUpdated={lastUpdated}
            onRefresh={fetchSignals} onGoSettings={() => setScreen("settings")} />}
    </SafeAreaView>
  );
}

function Tab({ label, active, onPress }) {
  return (
    <TouchableOpacity onPress={onPress}
      style={[styles.tab, active && styles.tabActive]}>
      <Text style={[styles.tabText, active && styles.tabTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

function StatusLine({ status, errorMsg, lastUpdated }) {
  let text = "";
  let color = "#8aa0c6";
  if (status === "loading") text = "Guncelleniyor…";
  else if (status === "error") { text = `Hata: ${errorMsg}`; color = "#e06c6c"; }
  else if (status === "ok")
    text = `Guncel · ${lastUpdated ? lastUpdated.toLocaleTimeString() : ""} · ${POLL_SECONDS}s'de bir`;
  else text = "Sunucu adresi girilmedi";
  return <Text style={[styles.statusLine, { color }]}>{text}</Text>;
}

function Signals({ signals, status, errorMsg, serverUrl, lastUpdated, onRefresh, onGoSettings }) {
  if (!serverUrl) {
    return (
      <View style={styles.center}>
        <Text style={styles.muted}>Once Ayarlar'dan sunucu adresini gir.</Text>
        <TouchableOpacity style={styles.btn} onPress={onGoSettings}>
          <Text style={styles.btnText}>Ayarlar'a git</Text>
        </TouchableOpacity>
      </View>
    );
  }
  return (
    <FlatList
      data={signals}
      keyExtractor={(s, i) => `${sigTime(s)}|${s.symbol}|${s.strategy}|${i}`}
      contentContainerStyle={signals.length ? styles.list : styles.center}
      refreshControl={
        <RefreshControl refreshing={status === "loading"} onRefresh={onRefresh}
          tintColor="#8aa0c6" />}
      ListHeaderComponent={
        <StatusLine status={status} errorMsg={errorMsg} lastUpdated={lastUpdated} />}
      ListEmptyComponent={
        status === "loading"
          ? <ActivityIndicator color="#8aa0c6" style={{ marginTop: 40 }} />
          : <Text style={styles.muted}>
              {status === "error" ? "Baglanti yok." : "Henuz sinyal yok."}
            </Text>}
      renderItem={({ item }) => <SignalCard s={item} />}
    />
  );
}

function SignalCard({ s }) {
  const strong = isStrong(s);
  const accent = strong ? "#e06c6c" : "#2c7be5";
  return (
    <View style={[styles.card, { borderLeftColor: accent }]}>
      <View style={styles.cardTop}>
        <Text style={styles.symbol}>{s.symbol}</Text>
        <View style={[styles.badge, { backgroundColor: accent }]}>
          <Text style={styles.badgeText}>
            {s.strategy} · {s.direction}{strong ? " · GUCLU" : ""}
          </Text>
        </View>
      </View>
      <Text style={styles.price}>Fiyat {s.price} · ufuk ~{s.horizon_hours}s</Text>
      {detailRows(s).map(([k, v]) => (
        <Text key={k} style={styles.detail}>{k}: <Text style={styles.detailVal}>{v}</Text></Text>
      ))}
      <Text style={styles.note}>{s.note}</Text>
      <Text style={styles.time}>{fmtTime(sigTime(s))}</Text>
    </View>
  );
}

function Settings({ draftUrl, setDraftUrl, onSave, notifOk, serverUrl }) {
  return (
    <View style={styles.settings}>
      <Text style={styles.label}>Sunucu adresi (Render URL)</Text>
      <TextInput
        style={styles.input}
        value={draftUrl}
        onChangeText={setDraftUrl}
        placeholder="https://signal-bot-xxxx.onrender.com"
        placeholderTextColor="#5b6b88"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />
      <TouchableOpacity style={styles.btn} onPress={onSave}>
        <Text style={styles.btnText}>Kaydet</Text>
      </TouchableOpacity>

      <View style={styles.infoBox}>
        <Text style={styles.infoTitle}>Durum</Text>
        <Text style={styles.infoLine}>
          Kayitli adres: {serverUrl ? serverUrl : "(yok)"}
        </Text>
        <Text style={styles.infoLine}>
          Bildirim izni: {notifOk ? "verildi ✓" : "verilmedi ✗"}
        </Text>
      </View>

      <Text style={styles.disclaimer}>
        Not: Uygulama yalnizca ACIKKEN sinyalleri kontrol eder ve yeni sinyalde
        yerel bildirim gosterir. Arka planda/kapaliyken bildirim gelmez — bunun
        icin Telegram ve email kanallari devrede. Ilk istek, ucretsiz sunucu
        uykudaysa 30-60 sn gecikebilir.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#0b1220" },
  header: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 4 },
  title: { color: "#eaf0fb", fontSize: 24, fontWeight: "700" },
  tabs: { flexDirection: "row", marginTop: 10, gap: 8 },
  tab: { paddingVertical: 6, paddingHorizontal: 14, borderRadius: 16, backgroundColor: "#16203a" },
  tabActive: { backgroundColor: "#2c7be5" },
  tabText: { color: "#8aa0c6", fontWeight: "600" },
  tabTextActive: { color: "#fff" },
  center: { flexGrow: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  muted: { color: "#8aa0c6", textAlign: "center", marginBottom: 16 },
  statusLine: { fontSize: 12, marginBottom: 8, paddingHorizontal: 2 },
  list: { padding: 12, paddingBottom: 32 },
  card: {
    backgroundColor: "#111a2e", borderRadius: 12, padding: 14, marginBottom: 10,
    borderLeftWidth: 4,
  },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  symbol: { color: "#eaf0fb", fontSize: 18, fontWeight: "700" },
  badge: { borderRadius: 8, paddingVertical: 3, paddingHorizontal: 8 },
  badgeText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  price: { color: "#c7d3ea", marginTop: 6, fontSize: 14 },
  detail: { color: "#8aa0c6", marginTop: 2, fontSize: 13 },
  detailVal: { color: "#c7d3ea", fontWeight: "600" },
  note: { color: "#9fb0cf", marginTop: 6, fontSize: 13, fontStyle: "italic" },
  time: { color: "#5b6b88", marginTop: 6, fontSize: 11 },
  settings: { padding: 16 },
  label: { color: "#c7d3ea", fontWeight: "600", marginBottom: 6 },
  input: {
    backgroundColor: "#111a2e", color: "#eaf0fb", borderRadius: 10, padding: 12,
    borderWidth: 1, borderColor: "#22304f",
  },
  btn: {
    backgroundColor: "#2c7be5", borderRadius: 10, padding: 12, alignItems: "center",
    marginTop: 12,
  },
  btnText: { color: "#fff", fontWeight: "700" },
  infoBox: { backgroundColor: "#111a2e", borderRadius: 10, padding: 12, marginTop: 20 },
  infoTitle: { color: "#eaf0fb", fontWeight: "700", marginBottom: 6 },
  infoLine: { color: "#8aa0c6", fontSize: 13, marginTop: 2 },
  disclaimer: { color: "#6f80a0", fontSize: 12, marginTop: 20, lineHeight: 18 },
});
