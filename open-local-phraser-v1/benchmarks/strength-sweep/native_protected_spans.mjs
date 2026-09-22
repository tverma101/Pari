import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const root = path.resolve(new URL("../..", import.meta.url).pathname);
const sourcePath = path.join(root, "src/lib/safety/protectedContent.ts");
const require = createRequire(import.meta.url);
const source = fs.readFileSync(sourcePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    esModuleInterop: true,
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
  fileName: sourcePath,
}).outputText;
const moduleValue = { exports: {} };
new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
  moduleValue.exports,
  require,
  moduleValue,
  sourcePath,
  path.dirname(sourcePath),
);

const inputs = JSON.parse(fs.readFileSync(0, "utf8"));
const rows = inputs.map((input) =>
  moduleValue.exports.extractProtectedSpans(String(input)).map(({ text, kind }) => ({ text, kind }))
);
process.stdout.write(JSON.stringify(rows));
