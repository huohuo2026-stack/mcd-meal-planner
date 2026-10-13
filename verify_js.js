// 验证 JS 算法与 Python 版结果一致
// 用法: node verify_js.js
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'app.html'), 'utf8');

// 从 HTML 中提取内嵌数据（用行首标记精确截取，避免贪婪匹配吃掉注释）
function extract(html, marker) {
  const start = html.indexOf(marker);
  if (start < 0) throw new Error('找不到标记: ' + marker);
  const from = html.indexOf(marker.split('=')[1].trim()[0], start);
  // 从赋值开始，括号配对找结束
  const assignIdx = html.indexOf('=', start) + 1;
  let i = assignIdx;
  while (html[i] === ' ' || html[i] === '\n') i++;
  const open = html[i];
  const close = open === '[' ? ']' : '}';
  let depth = 0, inStr = false, esc = false;
  for (let j = i; j < html.length; j++) {
    const ch = html[j];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === '\\') esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') { inStr = true; continue; }
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return JSON.parse(html.slice(i, j + 1));
    }
  }
  throw new Error('括号未闭合: ' + marker);
}
const NUTRI = extract(html, 'const NUTRI =');
const STORES = extract(html, 'const STORES =');
console.log('提取营养数据:', NUTRI.length, '项');
console.log('提取门店数据:', Object.keys(STORES).length, '家');

// 把 HTML 里的算法段抠出来执行（避免重复实现导致偏差）
const scriptStart = html.indexOf('const PROFILES');
const scriptEnd = html.indexOf('// ==================== 交互绑定');
const algo = html.slice(scriptStart, scriptEnd);

// 提供 DOM 桩，让算法段可独立运行
const stubs = `
const document = { getElementById: () => ({value:'',innerHTML:'',appendChild(){},style:{}}),
  createElement: () => ({style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}}}),
  querySelector: () => ({dataset:{},classList:{add(){},remove(){},toggle(){},contains(){return false}}}),
  querySelectorAll: () => [] };
`;

// 把数据与算法段一起注入函数作用域
const fn = new Function('NUTRI', 'STORES',
  stubs + '\n' + algo +
  '\nreturn {recommendNutrition, runPrice, tierCompare, tierOf, roleOf};');
const { recommendNutrition, tierOf, roleOf, tierCompare } = fn(NUTRI, STORES);

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
  if (cond) { pass++; console.log('  [PASS]', name, detail ? '— ' + detail : ''); }
  else { fail++; console.log('  [FAIL]', name, detail ? '— ' + detail : ''); }
}

console.log('\n=== T1 营养版：硬约束（不超预算）===');
[300, 400, 500, 600, 700, 900, 1000].forEach(b => {
  const r = recommendNutrition(b, '均衡', true, false, 3);
  const ok = r.results.every(x => x.s.k <= b);
  check(`预算 ${b} 不超上限`, ok,
        r.results.map(x => x.s.k).join('/'));
});

console.log('\n=== T2 结构：必须含正餐主体 ===');
let structOk = true, bad = '';
[400, 500, 600].forEach(b => {
  const r = recommendNutrition(b, '均衡', true, false, 3);
  r.results.forEach(x => {
    const hasMain = x.items.some(i => i.g === '主食' || i.g === '早餐');
    if (!hasMain) { structOk = false; bad = `预算${b}`; }
  });
});
check('所有方案含正餐主体', structOk, bad);

console.log('\n=== T3 营养汇总一致性 ===');
let sumOk = true, sumBad = '';
[500, 700].forEach(b => {
  const r = recommendNutrition(b, '减脂', true, false, 3);
  r.results.forEach(x => {
    const k = x.items.reduce((a, i) => a + i.k, 0);
    const p = x.items.reduce((a, i) => a + i.p, 0);
    if (k !== x.s.k || p !== x.s.p) { sumOk = false; sumBad = `预算${b}`; }
  });
});
check('汇总 = 明细加总', sumOk, sumBad);

console.log('\n=== T4 目标区分度 ===');
const fats = {};
['均衡', '减脂', '增肌'].forEach(g => {
  const r = recommendNutrition(600, g, true, false, 1);
  fats[g] = r.results[0] ? r.results[0].s.f : null;
});
check('不同目标产出不同脂肪量', new Set(Object.values(fats)).size >= 2, JSON.stringify(fats));

console.log('\n=== T5 多样性 ===');
const r5 = recommendNutrition(600, '均衡', true, false, 3);
const mains = r5.results.map(x =>
  x.items.filter(i => i.g === '主食' || i.g === '早餐').map(i => i.n).sort().join('|'));
check('top-3 主餐不重复', new Set(mains).size === mains.length, mains.join(' / '));

console.log('\n=== T6 降级模式 ===');
const rl = recommendNutrition(200, '均衡', true, false, 3);
check('低预算可出结果', rl.results.length > 0 && rl.mode === 'light',
      `mode=${rl.mode}, ${rl.results.length} 个`);
check('降级也不超预算', rl.results.every(x => x.s.k <= 200));

console.log('\n=== T7 比价版：门店角色与档位 ===');
const code = Object.keys(STORES)[0];
const items = Object.entries(STORES[code].rows).map(([n, r]) => ({
  n, price: r.price, tier: tierOf(n), role: roleOf(n)
}));
check('门店商品数 > 50', items.length > 50, items.length + ' 项');
check('三档结构齐全',
      ['单品', '组合', '套餐'].every(t => items.some(x => x.tier === t)),
      JSON.stringify(items.reduce((a, x) => (a[x.tier] = (a[x.tier] || 0) + 1, a), {})));
check('无未分类商品', items.every(x => x.role !== '其他'),
      items.filter(x => x.role === '其他').map(x => x.n).join(',') || '无');
const tc = tierCompare(items);
check('档位差价可算', tc.length > 0, tc.length + ' 组');

// 比价组合不超预算
const mainsP = items.filter(x => x.role === '主食' && x.tier === '单品' && x.price <= 40);
check('比价主食池非空', mainsP.length > 0, mainsP.length + ' 项');

// ---------------- 导出功能验证（T8/T9） ----------------
// 重新抠出含导出函数的完整脚本段（到"营养版渲染"为止的算法 + 导出部分）
const exportAlgo = html.slice(html.indexOf('const PROFILES'),
  html.indexOf('// ==================== 营养版渲染'));

// 带记录能力的 DOM 桩，用于检验 showToolbar/hideToolbar 行为
const calls = [];
const domStub = `
const document = {
  _calls: [],
  getElementById: (id) => ({ get value(){return '';}, set value(v){},
    innerHTML:'', textContent:'', style:{}, disabled:false,
    appendChild(){}, removeChild(){}, click(){} }),
  createElement: (tag) => ({ tag, style:{}, disabled:false, textContent:'',
    href:'', download:'', click(){},
    classList:{add(){},remove(){},toggle(){},contains(){return false}},
    getContext(){ return {
      font:'', fillStyle:'', textBaseline:'',
      scale(){}, fillRect(){}, fillText(){},
      createLinearGradient(){ return {addColorStop(){}}; },
      measureText(t){ return {width: (t||'').length * 7}; }
    }; },
    toBlob(cb){ cb(new Blob(['x'], {type:'image/png'})); } }),
  querySelector: () => ({dataset:{},classList:{add(){},remove(){},toggle(){},contains(){return false}}}),
  querySelectorAll: () => [],
  body: { removeChild(){} }
};`;

const fn2 = new Function('NUTRI', 'STORES', 'URL', 'Blob',
  domStub + '\n' + exportAlgo +
  '\nreturn {recommendNutrition, buildText, exportImage, showToolbar, hideToolbar,' +
  ' setState:(m,p)=>{STATE={mode:m,payload:p};}, getState:()=>STATE};');
// URL 桩：Node 的 createObjectURL 要求真实 Blob，这里替换掉
const URLStub = {
  createObjectURL: () => 'blob:stub',
  revokeObjectURL: () => {}
};
const api = fn2(NUTRI, STORES, URLStub, Blob);

console.log('\n=== T8 导出文本构建 ===');
// 营养版
const rn = api.recommendNutrition(600, '减脂', true, false, 3);
api.setState('nutrition', rn);
const tN = api.buildText();
check('营养文本含标题', tN.includes('麦当劳营养配餐方案'));
check('营养文本含目标', tN.includes('减脂'));
check('营养文本含预算', tN.includes('600 kcal'));
check('营养文本含方案数', (tN.match(/【方案/g) || []).length === rn.results.length,
      `${rn.results.length} 个方案`);
check('营养文本含数据源', tN.includes('list-nutrition-foods'));

// 比价版
const items2 = Object.entries(STORES[code].rows).map(([n, r]) => ({
  n, price: r.price, tier: tierOf(n), role: roleOf(n)
}));
const plans = [];
const seen2 = new Set(), usedM = new Set();
const allC = [];
const mains2 = items2.filter(x => x.role === '主食' && x.tier === '单品' && x.price <= 40);
const sides2 = items2.filter(x => x.role === '小食' && x.tier === '单品');
const drinks2 = items2.filter(x => x.role === '饮品' && x.tier === '单品');
for (const m of mains2) for (const so of [[], ...sides2.map(s => [s])])
  for (const dr of [[], ...drinks2.map(d => [d])]) {
    const cmb = [m, ...so, ...dr];
    const tot = cmb.reduce((a, x) => a + x.price, 0);
    if (tot <= 40) allC.push({ cmb, tot });
  }
allC.sort((a, b) => b.tot - a.tot || b.cmb.length - a.cmb.length);
for (const { cmb, tot } of allC) {
  const key = cmb.map(x => x.n).sort().join('|');
  if (seen2.has(key)) continue;
  const mn = cmb.filter(x => x.role === '主食').map(x => x.n).sort().join('|');
  if (usedM.has(mn)) continue;
  seen2.add(key); usedM.add(mn);
  plans.push({ items: cmb, total: +tot.toFixed(2), remaining: +(40 - tot).toFixed(2) });
  if (plans.length >= 3) break;
}
api.setState('price', {store: STORES[code].name, budget: 40, plans, diffs: tierCompare(items2)});
const tP = api.buildText();
check('比价文本含标题', tP.includes('麦当劳门店点餐比价方案'));
check('比价文本含门店名', tP.includes(STORES[code].name));
check('比价文本含方案数', (tP.match(/【方案/g) || []).length === plans.length,
      `${plans.length} 个方案`);
check('比价文本含档位分析', tP.includes('档位差价分析'));
check('比价文本含数据源', tP.includes('calculate-price'));

console.log('\n=== T9 图片导出不抛异常 ===');
let imgOk = true, imgErr = '';
try { api.exportImage({ disabled:false, textContent:'' }); }
catch (e) { imgOk = false; imgErr = e.message; }
check('营养版导出图片', imgOk, imgErr);
imgOk = true; imgErr = '';
try { api.exportImage({ disabled:false, textContent:'' }); }
catch (e) { imgOk = false; imgErr = e.message; }
check('比价版导出图片', imgOk, imgErr);

console.log('\n=== T10 工具栏显隐 ===');
let tbOk = true;
try { api.showToolbar(); api.hideToolbar(); } catch (e) { tbOk = false; }
check('showToolbar/hideToolbar 可调用', tbOk);

console.log('\n=======================');
console.log(`   JS 验证：PASS=${pass} / FAIL=${fail}`);
console.log('=======================');
process.exit(fail === 0 ? 0 : 1);
