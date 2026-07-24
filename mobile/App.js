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
const K_DELIVERY_PREFIX = "signalDeliveryStateV3";
const MAX_OBSERVED_IDS = 1000;
const MAX_DELIVERED_IDS = 500;
const MAX_FAILED_IDS = 500;
const MAX_PENDING = 100;
const MAX_RETRIES_PER_POLL = 3;
const MAX_DELIVERY_ATTEMPTS = 3;
const PENDING_MAX_AGE_MS = 15 * 60 * 1000;
const MAX_NEW_DELIVERIES_PER_POLL = 5;
const NEW_DELIVERY_MAX_AGE_MS = 15 * 60 * 1000;

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
const signalId = (s) => {
  const eventId = String(s.event_id || "").trim();
  if (eventId) return `event:${eventId}`;
  // Eski sunucular icin indeks/siralama kullanmayan, yeniden cekimlerde sabit kimlik.
  return [
    "legacy", sigTime(s), s.symbol, s.strategy, s.direction, s.price,
    s.horizon_hours,
  ].map((v) => String(v ?? "")).join("|");
};
const canPush = (s) => s.push_allowed === true && s.suppressed !== true;
const isStrong = (s) => s.strength === "STRONG";

function suppressionText(s) {
  if (canPush(s)) return "";
  const labels = {
    confidence_below_threshold: "guven esigi alti",
    scan_push_cap: "tarama bildirim kotasi",
  };
  const reasons = String(s.suppression_reason || "")
    .split(",").map((x) => x.trim()).filter(Boolean)
    .map((x) => labels[x] || x);
  return reasons.length ? reasons.join(", ") : "sunucu push izni vermedi";
}

function hashString(value) {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

const deliveryStorageKey = (sourceUrl) =>
  `${K_DELIVERY_PREFIX}:${hashString(sourceUrl)}`;

function boundedStrings(values, limit) {
  const out = [];
  const seen = new Set();
  for (const value of values || []) {
    if (typeof value !== "string" || !value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out.slice(-limit);
}

function normalizeSignal(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const strategy = typeof raw.strategy === "string" ? raw.strategy.trim() : "";
  const symbol = typeof raw.symbol === "string" ? raw.symbol.trim() : "";
  const direction = typeof raw.direction === "string" ? raw.direction.trim() : "";
  const notifiedAt = typeof raw.notified_at === "string" ? raw.notified_at : "";
  const barTime = typeof raw.bar_time === "string" ? raw.bar_time : "";
  const timeText = notifiedAt || barTime;
  const timeMs = Date.parse(timeText);
  const price = Number(raw.price);
  const horizonHours = Number(raw.horizon_hours);
  if (!strategy || !symbol || !direction || !timeText
      || Number.isNaN(timeMs) || !Number.isFinite(price)
      || price <= 0 || !Number.isFinite(horizonHours)
      || horizonHours <= 0) return null;

  return {
    ...raw,
    strategy,
    symbol,
    direction,
    price,
    horizon_hours: horizonHours,
    note: typeof raw.note === "string" ? raw.note : "",
    notified_at: notifiedAt,
    bar_time: barTime,
    event_id: (typeof raw.event_id === "string"
      ? raw.event_id.trim() : ""),
    push_allowed: raw.push_allowed === true,
    suppressed: raw.suppressed === true,
    suppression_reason: (typeof raw.suppression_reason === "string"
      ? raw.suppression_reason : ""),
  };
}

function notificationSnapshot(s) {
  return {
    strategy: s.strategy,
    symbol: s.symbol,
    direction: s.direction,
    price: s.price,
    horizon_hours: s.horizon_hours,
    note: s.note,
    strength: s.strength,
    event_id: s.event_id,
    notified_at: s.notified_at,
    bar_time: s.bar_time,
    push_allowed: s.push_allowed,
    suppressed: s.suppressed,
    suppression_reason: s.suppression_reason,
  };
}

function emptyDeliveryState(sourceUrl) {
  return {
    sourceUrl,
    initialized: false,
    watermarkMs: 0,
    observed: new Set(),
    delivered: new Set(),
    failed: new Set(),
    pending: new Map(),
  };
}

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
    const permission = await Notifications.getPermissionsAsync();
    if (!(permission.granted || permission.status === "granted")) return false;
    await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: { symbol: s.symbol, eventId: String(s.event_id || "") },
      },
      trigger: null,               // hemen
    });
    return true;
  } catch (e) {
    // bildirim hatasi akisi bozmasin
    console.warn("local notification error", e);
    return false;
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

  const deliveryStateRef = useRef(emptyDeliveryState(""));
  const pollRef = useRef(null);
  const serverUrlRef = useRef("");
  const requestRef = useRef(null);
  const requestGenerationRef = useRef(0);

  // Ilk acilis: kayitli adresi ve bildirim iznini yukle.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const u = normalizeUrl(await AsyncStorage.getItem(K_URL));
      const ok = await ensureNotificationPermission();
      if (cancelled) return;
      serverUrlRef.current = u;
      setServerUrl(u);
      setDraftUrl(u);
      setNotifOk(ok);
    })();
    return () => { cancelled = true; };
  }, []);

  const loadDeliveryState = useCallback(async (sourceUrl) => {
    const state = emptyDeliveryState(sourceUrl);
    try {
      const raw = await AsyncStorage.getItem(deliveryStorageKey(sourceUrl));
      if (raw === null) return state;
      const saved = JSON.parse(raw);
      if (!saved || saved.version !== 3 || saved.sourceUrl !== sourceUrl
          || !Array.isArray(saved.observed)
          || !Array.isArray(saved.delivered)
          || !Array.isArray(saved.failed)
          || !Array.isArray(saved.pending)) return state;
      state.initialized = saved.initialized === true;
      state.watermarkMs = (Number.isFinite(Number(saved.watermarkMs))
        ? Math.max(0, Number(saved.watermarkMs)) : 0);
      state.observed = new Set(boundedStrings(
        saved.observed, MAX_OBSERVED_IDS));
      state.delivered = new Set(boundedStrings(
        saved.delivered, MAX_DELIVERED_IDS));
      state.failed = new Set(boundedStrings(saved.failed, MAX_FAILED_IDS));
      const now = Date.now();
      for (const item of Array.isArray(saved.pending) ? saved.pending : []) {
        if (!item || typeof item !== "object") continue;
        const id = typeof item.id === "string" ? item.id : "";
        const signal = normalizeSignal(item.signal);
        const attempts = Number(item.attempts);
        const firstSeenAt = Number(item.firstSeenAt);
        const nextRetryAt = Number(item.nextRetryAt);
        if (!id || !signal || !canPush(signal)
            || !Number.isInteger(attempts) || attempts < 1
            || attempts >= MAX_DELIVERY_ATTEMPTS
            || !Number.isFinite(firstSeenAt) || !Number.isFinite(nextRetryAt)
            || now - firstSeenAt > PENDING_MAX_AGE_MS) {
          if (id) state.failed.add(id);
          continue;
        }
        state.pending.set(id, {
          id, signal, attempts, firstSeenAt, nextRetryAt,
        });
      }
    } catch (e) {
      // Bozuk storage guvenli bicimde yeni baseline'a doner.
      console.warn("delivery state load error", e);
      return emptyDeliveryState(sourceUrl);
    }
    return state;
  }, []);

  const persistDeliveryState = useCallback(async (state) => {
    state.observed = new Set(boundedStrings(
      [...state.observed], MAX_OBSERVED_IDS));
    state.delivered = new Set(boundedStrings(
      [...state.delivered], MAX_DELIVERED_IDS));
    state.failed = new Set(boundedStrings([...state.failed], MAX_FAILED_IDS));
    const pending = [...state.pending.values()].slice(-MAX_PENDING);
    state.pending = new Map(pending.map((item) => [item.id, item]));
    const payload = {
      version: 3,
      sourceUrl: state.sourceUrl,
      initialized: state.initialized,
      watermarkMs: state.watermarkMs,
      observed: [...state.observed],
      delivered: [...state.delivered],
      failed: [...state.failed],
      pending,
    };
    try {
      await AsyncStorage.setItem(
        deliveryStorageKey(state.sourceUrl), JSON.stringify(payload));
      return true;
    } catch (e) {
      console.warn("delivery state save error", e);
      return false;
    }
  }, []);

  const processNewSignals = useCallback(async (list, sourceUrl, generation) => {
    const state = deliveryStateRef.current;
    if (state.sourceUrl !== sourceUrl) return;
    // list: sunucudan (yeni->eski). Islemek icin eskiden yeniye sirala.
    const asc = [...list].sort((a, b) => sigMs(a) - sigMs(b));

    if (!state.initialized) {
      // Her yeni sunucu adresi kendi baseline'ini olusturur; gecmis yagmuru yok.
      for (const s of asc) state.observed.add(signalId(s));
      const newest = asc.length ? sigMs(asc[asc.length - 1]) : Date.now();
      state.watermarkMs = newest || Date.now();
      state.initialized = true;
      await persistDeliveryState(state);
      return;
    }

    const baselineWatermark = state.watermarkMs;
    let hi = baselineWatermark;
    let changed = false;
    const freshnessNow = Date.now();
    const deliverableIds = new Set(asc.filter((s) => {
      const t = sigMs(s);
      return !state.observed.has(signalId(s)) && canPush(s)
        && t >= baselineWatermark
        && freshnessNow - t <= NEW_DELIVERY_MAX_AGE_MS;
    }).slice(-MAX_NEW_DELIVERIES_PER_POLL).map(signalId));
    for (const s of asc) {
      if (requestGenerationRef.current !== generation
          || serverUrlRef.current !== sourceUrl) break;
      const id = signalId(s);
      if (state.observed.has(id)) continue;
      state.observed.add(id);
      changed = true;

      const t = sigMs(s);
      if (deliverableIds.has(id)
          && requestGenerationRef.current === generation
          && serverUrlRef.current === sourceUrl) {
        const delivered = await fireLocalNotification(s);
        if (delivered) {
          state.delivered.add(id);
        } else {
          const now = Date.now();
          state.pending.set(id, {
            id,
            signal: notificationSnapshot(s),
            attempts: 1,
            firstSeenAt: now,
            nextRetryAt: now + 60 * 1000,
          });
        }
      } else if (canPush(s) && t >= baselineWatermark) {
        // Eski/birikmis kayitlar listede kalir ama sonradan bildirim yagdirmaz.
        state.failed.add(id);
      }
      if (t > hi) hi = t;
    }

    state.watermarkMs = hi;
    const now = Date.now();
    let retries = 0;
    for (const [id, item] of [...state.pending]) {
      if (state.delivered.has(id)) {
        state.pending.delete(id);
        changed = true;
        continue;
      }
      if (now - item.firstSeenAt > PENDING_MAX_AGE_MS
          || item.attempts >= MAX_DELIVERY_ATTEMPTS) {
        state.pending.delete(id);
        state.failed.add(id);
        changed = true;
        continue;
      }
      if (item.nextRetryAt > now || retries >= MAX_RETRIES_PER_POLL) continue;
      if (requestGenerationRef.current !== generation
          || serverUrlRef.current !== sourceUrl) break;
      retries += 1;
      const delivered = await fireLocalNotification(item.signal);
      changed = true;
      if (delivered) {
        state.pending.delete(id);
        state.delivered.add(id);
      } else {
        item.attempts += 1;
        if (item.attempts >= MAX_DELIVERY_ATTEMPTS) {
          state.pending.delete(id);
          state.failed.add(id);
        } else {
          const delayMinutes = item.attempts === 2 ? 5 : 10;
          item.nextRetryAt = Date.now() + delayMinutes * 60 * 1000;
          state.pending.set(id, item);
        }
      }
    }

    if (changed) await persistDeliveryState(state);
  }, [persistDeliveryState]);

  const fetchSignals = useCallback(async () => {
    const base = normalizeUrl(serverUrlRef.current);
    if (!base) { setStatus("idle"); return; }
    if (deliveryStateRef.current.sourceUrl !== base) return;
    const generation = requestGenerationRef.current + 1;
    requestGenerationRef.current = generation;
    if (requestRef.current) requestRef.current.abort();
    const ctrl = new AbortController();
    requestRef.current = ctrl;
    let timedOut = false;
    const to = setTimeout(() => {
      timedOut = true;
      ctrl.abort();
    }, 15000);
    setStatus((p) => (p === "ok" ? "ok" : "loading"));
    try {
      const res = await fetch(`${base}/signals/latest?limit=${FETCH_LIMIT}`,
        { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (generation !== requestGenerationRef.current
          || base !== serverUrlRef.current) return;
      const rows = Array.isArray(data.signals) ? data.signals : [];
      const list = rows.map(normalizeSignal).filter(Boolean);
      if (list.length !== rows.length)
        console.warn(`dropped ${rows.length - list.length} malformed signal rows`);
      setSignals(list);
      await processNewSignals(list, base, generation);
      if (generation === requestGenerationRef.current
          && base === serverUrlRef.current) {
        setStatus("ok");
        setErrorMsg("");
        setLastUpdated(new Date());
      }
    } catch (e) {
      if (generation !== requestGenerationRef.current
          || base !== serverUrlRef.current) return;
      setStatus("error");
      setErrorMsg(e.name === "AbortError" && timedOut
        ? "Zaman asimi (sunucu uykuda olabilir)"
        : String(e.message || e));
    } finally {
      clearTimeout(to);
      if (generation === requestGenerationRef.current)
        requestRef.current = null;
    }
  }, [processNewSignals]);

  // polling + AppState (arka plana gecince duraklat, one gelince hemen cek)
  useEffect(() => {
    const sourceUrl = normalizeUrl(serverUrl);
    serverUrlRef.current = sourceUrl;
    requestGenerationRef.current += 1;
    if (requestRef.current) requestRef.current.abort();
    requestRef.current = null;
    setSignals([]);
    if (!sourceUrl) {
      deliveryStateRef.current = emptyDeliveryState("");
      setStatus("idle");
      return undefined;
    }

    let disposed = false;
    const startPoll = () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(fetchSignals, POLL_SECONDS * 1000);
    };
    const ready = loadDeliveryState(sourceUrl).then((state) => {
      if (disposed || serverUrlRef.current !== sourceUrl) return false;
      deliveryStateRef.current = state;
      return true;
    });
    ready.then((ok) => {
      if (ok && AppState.currentState === "active") {
        fetchSignals();
        startPoll();
      }
    });
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") {
        Notifications.getPermissionsAsync().then((permission) => {
          if (!disposed)
            setNotifOk(permission.granted || permission.status === "granted");
        }).catch(() => { if (!disposed) setNotifOk(false); });
        ready.then((ok) => {
          if (ok && !disposed) { fetchSignals(); startPoll(); }
        });
      } else {
        requestGenerationRef.current += 1;
        if (requestRef.current) requestRef.current.abort();
        requestRef.current = null;
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    });
    return () => {
      disposed = true;
      requestGenerationRef.current += 1;
      if (requestRef.current) requestRef.current.abort();
      requestRef.current = null;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      sub.remove();
    };
  }, [serverUrl, fetchSignals, loadDeliveryState]);

  const saveUrl = async () => {
    const u = normalizeUrl(draftUrl);
    const unchanged = u === serverUrlRef.current;
    requestGenerationRef.current += 1;
    if (requestRef.current) requestRef.current.abort();
    requestRef.current = null;
    serverUrlRef.current = u;
    await AsyncStorage.setItem(K_URL, u);
    setServerUrl(u);
    setScreen("signals");
    if (unchanged && u) fetchSignals();
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
      keyExtractor={(s, i) => `${signalId(s)}|${i}`}
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
  const silentReason = suppressionText(s);
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
      {silentReason
        ? <Text style={styles.silent}>🔕 Sessiz kayıt · {silentReason}</Text>
        : null}
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
      <Text style={styles.label}>Sunucu adresi (tablet / VPS)</Text>
      <TextInput
        style={styles.input}
        value={draftUrl}
        onChangeText={setDraftUrl}
        placeholder="http://192.168.1.50:8000"
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
        icin Telegram ve email kanallari devrede.
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
  silent: {
    color: "#d3a84f", backgroundColor: "#2a2417", borderRadius: 6,
    paddingVertical: 4, paddingHorizontal: 7, marginTop: 7, fontSize: 12,
  },
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
