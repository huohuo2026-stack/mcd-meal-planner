// 静态结构完整性校验：确认导出功能各部件都已注入 app.html
const fs = require('fs');
const path = require('path');
const h = fs.readFileSync(path.join(__dirname, 'app.html'), 'utf8');

let ok = true;
const need = [
  ['工具栏按钮 exportImage', 'onclick="exportImage(this)"'],
  ['工具栏按钮 copyText', 'onclick="copyText()"'],
  ['toolbar 容器', 'id="toolbar"'],
  ['tb-msg 提示位', 'id="tb-msg"'],
  ['STATE 声明', 'let STATE = {mode:null, payload:null}'],
  ['hideToolbar 定义', 'function hideToolbar()'],
  ['showToolbar 定义', 'function showToolbar()'],
  ['buildText 定义', 'function buildText()'],
  ['exportImage 定义', 'function exportImage(btn)'],
  ['fallbackCopy 定义', 'function fallbackCopy('],
  ['营养版设 STATE', "STATE = {mode:'nutrition', payload:r}"],
  ['比价版设 STATE', "STATE = {mode:'price', payload:"],
  ['切页隐藏工具栏', 'hideToolbar();'],
  ['Canvas 2x 高清', 'const SCALE = 2'],
  ['PNG 下载', "a.download = `麦当劳方案_"],
];

console.log('=== 结构完整性 ===');
need.forEach(([n, s]) => {
  const f = h.includes(s);
  if (!f) ok = false;
  console.log((f ? '[OK]   ' : '[MISS] ') + n);
});

const cnt = (s) => h.split(s).length - 1;
console.log('--- 标签配平 ---');
const scriptOk = cnt('<script') === cnt('</script>');
const styleOk = cnt('<style') === cnt('</style>');
const divOpen = cnt('<div'), divClose = cnt('</div>');
if (!scriptOk || !styleOk) ok = false;
console.log('script:', cnt('<script'), '/', cnt('</script>'), scriptOk ? 'OK' : 'MISMATCH');
console.log('style :', cnt('<style'), '/', cnt('</style>'), styleOk ? 'OK' : 'MISMATCH');
console.log('div   :', divOpen, '/', divClose, divOpen === divClose ? 'OK' : 'DIFF(容忍自闭合)');
console.log('大小  :', (h.length / 1024).toFixed(1), 'KB');

console.log('\n结论:', ok ? '✅ 结构完整' : '❌ 缺失部件');
process.exit(ok ? 0 : 1);
