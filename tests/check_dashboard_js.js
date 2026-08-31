const fs = require("fs");

const html = fs.readFileSync("dashboard.html", "utf8");
const match = html.match(/<script>([\s\S]*)<\/script>/);
if (!match) throw new Error("dashboard script bulunamadi");
const script = match[1].replace(
  'const DATA_URL="{{DATA_URL}}";',
  'const DATA_URL="./data.json";'
);
new Function(script);
console.log(`dashboard-js-ok ${script.length}`);
