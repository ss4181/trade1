// Synthetic display fixtures only: never read bot state, .env or private archives.
module.exports = function fixture() {
  const now = new Date().toISOString();
  const old = new Date(Date.now()-86400000).toISOString();
  const counts = {hit:1,missed:1,pending:0,unavailable:0,resolved:2,hit_rate_pct:50};
  const row = {event_id:'fixture-g1',t:old,strategy:'G1',symbol:'BTCUSDT',direction:'LONG',
    universe:'fixture',config_version:'v3-fresh-ask',engine_version:'fixture',engine_config_hash:'fixture',
    performance_market:'um_perp',confidence:'GOZLEM',notification_status:'GONDERILDI',
    delivery_confirmed:true,entry:100,signal_price:100.1,signal_price_source:'usdm_book_best_ask_after_validation',
    entry_quote:{ask:100.1,spread_bps:2,age_seconds:1},entry_basis:'next_bar_open',
    status:'OLGUN',horizon_h:4,pnl_pct:1.88,note:'Sentetik test verisi',why:'Test koşulu',
    measurement_version:'signal-reference-touch-1m-v2'};
  const sample = {observed_hit_pct_all:50,hit:1,pending:1,unavailable:0,median_hours_to_hit_upper:4};
  return {now,strategies:[],signals:[row,{...row,event_id:'fixture-g2',strategy:'G2',symbol:'ETHUSDT',
      measurement_version:'g2-scheduled-bracket-v1',entry_quote:null,
      price_target:{g2_bracket:{status:'PENDING'},targets:[],success_status:'PENDING'}}],docs:{},
    status:{interval_min:5,symbols:89,last_scan:now,user_success_target_pct:2,round_trip_cost_bps:12,
      price_target_levels_pct:[2,3,5,10],price_target_notify_levels_pct:[2,3],
      research_reports:{source_label:'TABLET-ANA · TEST',runtime_source:'Termux / tablet',
        archive_files_present:true,archive_collection_enabled:true,weekly_weekday_utc:0,weekly_hour_utc:6,
        monthly_interval_days:30,
        weekly:{enabled:true,last_status:'sent',last_sent_at_utc:now,last_archive:{rows:123,last_record_at_utc:old}},
        monthly:{enabled:true,last_status:'error',retry_at_utc:now}},
      market_regime:{fresh:true,label:'BULL',subtype:'bull_moderate',data_close_at:now}},
    regime_performance:{historical:{available:true,report_file:'fixture-only.json',summaries:
      ['bull_moderate','bull_strong','bull_quiet'].map(group=>({strategy:'G1_PROXY',universe:'fixture',group,n:2,days:2,cutoff_ms:Date.now(),tp2:sample,tp3:sample}))},
      live:{rows:[{...row,market:'um_perp',regime:'BULL',subtype:'bull_moderate',n:2,tp2:counts,tp3:counts}]}},
  };
};
