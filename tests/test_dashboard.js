// No browser/network: validate the published script and price precision.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const line = script.split('\n').find(line => line.startsWith('const price='));
const price = vm.runInNewContext(line + '; price');
assert.equal(price(1000000), '1000000');
assert.equal(price(100), '100');
assert.equal(Number(price(0.00000000001)), 0.00000000001);
assert.equal(price(null), '—');
assert.equal(price(Infinity), '—');
assert.equal(price(NaN), '—');
assert.ok(html.includes('Kalite Kontrol CSV'));
assert.ok(html.includes('Kısmi teslim'));
console.log('PASS dashboard syntax, price precision, delivery/QC controls');
