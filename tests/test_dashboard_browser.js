// Usage: NODE_PATH=<playwright packages> node tests/test_dashboard_browser.js <dashboard JSON>
// Uses local fixtures only; no live bot, Telegram, or remote browser requests.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const html=fs.readFileSync(path.join(root,'dashboard.html'),'utf8').replace('{{DATA_URL}}','https://dashboard.test/data');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'America/New_York'});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let mode='ok';
    await page.route('**/*',async route=>{
      if(route.request().url()==='https://dashboard.test/')return route.fulfill({contentType:'text/html',body:html});
      if(mode==='error')return route.fulfill({status:503,body:'unavailable'});
      return route.fulfill({contentType:'application/json',body:JSON.stringify(mode==='invalid'?{error:'unavailable'}:data)});
    });
    await page.goto('https://dashboard.test/');
    await page.waitForFunction(()=>document.querySelector('#rows').textContent.includes('G1'));
    assert.equal(await page.locator('#rows tr.signal').count(),data.signals.length);
    assert.ok((await page.locator('#regimeRows').textContent()).includes('G1 tarihsel vekili'));
    assert.equal(await page.evaluate(()=>trTime('2026-09-24T12:00:00Z')), '24.09.2026 15:00:00 TRT');
    await page.screenshot({path:path.join(root,'tmp/dashboard-desktop.png'),fullPage:false});
    await page.selectOption('#regimeStrategy','G1_PROXY');
    assert.equal(await page.locator('#regimeRows tr').count(),3);
    await page.selectOption('#regimeStrategy','');await page.selectOption('#regimeSource','live');
    assert.ok((await page.locator('#regimeNote').textContent()).includes('Her yayında'));
    await page.selectOption('#fStrat','G2');
    assert.equal(await page.locator('#rows tr.signal').count(),data.signals.filter(r=>r.strategy==='G2').length);
    assert.ok(!(await page.locator('#rows .targetList').allTextContents()).join(' ').includes('TP2…'));
    await page.setViewportSize({width:375,height:812});
    assert.equal(await page.locator('.historyTable').isVisible(),false);
    assert.ok(await page.locator('#mobileSignals').isVisible());
    await page.click('#reset');
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(root,'tmp/dashboard-mobile.png'),fullPage:false});
    const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth&&getComputedStyle(e).display!=='none').map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right]).slice(0,20));
    if(overflow.length)console.log(overflow);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile page overflows');
    await page.locator('#mobileSignals details').first().locator('summary').click();
    assert.ok(await page.locator('#mobileSignals details').first().evaluate(e=>e.open));
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile details overflow');
    await page.selectOption('#fStrat','G1');
    await page.evaluate(()=>load());
    assert.equal(await page.inputValue('#fStrat'),'G1','refresh lost filter');
    const count=await page.locator('#rows tr.signal').count();
    for(const state of ['error','invalid']){mode=state;await page.evaluate(()=>load());
      assert.ok((await page.locator('#freshness').textContent()).includes('Güncel veri doğrulanamadı'));
      assert.equal(await page.locator('#rows tr.signal').count(),count);
    }
    assert.equal(await page.evaluate(()=>freshnessInfo({now:'2000-01-01T00:00:00Z'}).stale),true);
    assert.deepEqual(errors,[]);
    console.log('PASS desktop/mobile, TRT, research/live regimes, filters, refresh, stale/invalid/failed data');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
