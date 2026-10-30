// 仅离线浏览器：所有请求拦截，无真实服务启停、模型或恢复。
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const root=path.resolve(__dirname,'..'),dist=path.join(root,'web/dist');
 const output=path.join(root,'runtime/release-verification');fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const checks=[],errors=[],writes=[];
 try {
  const context=await browser.newContext({reducedMotion:'reduce'});
  await context.route('**/*',route=>{
   const req=route.request(),url=new URL(req.url());
   if(req.method()!=='GET'){writes.push(url.pathname);return route.abort();}
   if(url.origin!=='https://reops-release-fixture.invalid')return route.abort();
   if(url.pathname.startsWith('/api/'))return route.fulfill({status:503,json:{}});
   const file=path.resolve(dist,'.'+url.pathname);
   if(!file.startsWith(dist+path.sep)&&file!==dist)return route.abort();
   return route.fulfill({path:fs.existsSync(file)&&fs.statSync(file).isFile()?file:path.join(dist,'index.html')});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  for(const width of [1440,390])for(const locale of ['zh-CN','en']){
   await page.setViewportSize({width,height:960});
   await page.addInitScript(value=>localStorage.setItem('reops.locale',value),locale);
   for(const pathname of ['/', '/architecture','/workbench?source=offline_fixture','/knowledge-retrieval?source=offline_fixture','/recovery','/api']){
    await page.goto('https://reops-release-fixture.invalid'+pathname);
    await page.locator('main').waitFor();await page.evaluate(()=>document.fonts.ready);
    await page.waitForTimeout(150);
    const state=await page.evaluate(()=>({
     lang:document.documentElement.lang,overflow:document.documentElement.scrollWidth>innerWidth+1,
     github:[...document.querySelectorAll('a')].filter(a=>/github/i.test(a.textContent)||/github\.com/.test(a.href)).map(a=>a.href),
     logo:document.querySelector('.navbar-brand img')?.naturalWidth,
    }));
    assert.equal(state.lang,locale);assert.equal(state.overflow,false,pathname);
    if(pathname==='/workbench?source=offline_fixture'){
     await page.waitForFunction(()=>document.querySelector('.wb-toolbar select')?.value==='offline_fixture'&&document.querySelectorAll('.wb-target').length>0);
     assert.equal(await page.locator('.wb-run-shell').count(),0);
    }
    assert.equal(state.logo,865);assert(state.github.length>0);
    assert(state.github.every(url=>url==='https://github.com/magic12222/reops-release'));
    checks.push({width,locale,pathname,...state});
    if(pathname==='/workbench?source=offline_fixture'&&locale==='zh-CN')await page.screenshot({path:path.join(output,`workbench-${width}.png`),fullPage:true});
   }
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify({checks,errors,writes},null,2));
  console.log(JSON.stringify({checks:checks.length,errors,writes}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
