const fs = require("node:fs");
const path = require("node:path");
const parser = require("@babel/parser");

const root = __dirname;
for (const name of ["App.js", "index.js"]) {
  const source = fs.readFileSync(path.join(root, name), "utf8");
  parser.parse(source, {
    sourceType: "module",
    plugins: ["jsx"],
  });
}

for (const name of ["app.json", "package.json"]) {
  JSON.parse(fs.readFileSync(path.join(root, name), "utf8"));
}

console.log("mobile syntax/config checks: OK");
