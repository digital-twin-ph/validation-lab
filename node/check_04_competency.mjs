// Check 04: executable competency questions.
// Builds the run graph from an exported Fieldwork receipt, answers each question with SPARQL,
// and compares the measured answer with the status documented in Fieldwork's competency-question
// list. A disagreement is the finding: either the graph lost a fact or the list is stale.
// Design record: fieldwork/docs/experiments/41-validation-lab.md
import {createHash} from 'node:crypto';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {Parser,Store,DataFactory} from 'n3';
import {QueryEngine} from '@comunica/query-sparql-rdfjs';
import {QUESTIONS} from './cq/questions.mjs';
const {namedNode:N,literal:L,quad:Q}=DataFactory;

async function verified(path){
  const bytes=await readFile(path);
  const digest=createHash('sha256').update(bytes).digest('hex');
  const expected=(await readFile(path+'.sha256','utf8')).split(/\s+/)[0];
  if(digest!==expected)throw new Error(`Fixture hash mismatch for ${path}`);
  return {text:bytes.toString('utf8'),digest};
}

/** Assembles the same graph a reviewer sees: provenance, receipt facts and ground conclusions.
 *  Rule formulas are deliberately excluded; they are parsed as N3 elsewhere and are not data. */
function runGraph(run){
  const store=new Store();
  store.addQuads(new Parser().parse(run.provenanceN3||''));
  for(const receipt of run.receipts||[]){
    store.addQuads(new Parser().parse(receipt.facts||''));
    for(const c of receipt.conclusions||[]){
      const object=c.objectType==='NamedNode'?N(c.object):L(c.object,c.datatype?N(c.datatype):undefined);
      store.addQuad(Q(N(c.subject),N(c.predicate),object));
    }
  }
  return store;
}

/** Reads the documented status so the runner can report drift rather than assume agreement. */
async function documentedStatuses(path){
  const text=await readFile(path,'utf8');const statuses={};
  for(const line of text.split('\n')){
    const m=line.match(/^\|\s*(S?\d+[a-z]?|[PDEVGR]\d+[a-z]?)\s*\|.*\|\s*(\*\*)?([A-Za-z ,:]+?)(\*\*)?\s*\|\s*$/);
    if(m)statuses[m[1]]=m[3].trim().toLowerCase().replace(/[,:].*$/,'');
  }
  return statuses;
}

export async function run(receiptPath,questionsPath){
  const {text,digest}=await verified(receiptPath);
  const run=JSON.parse(text);
  const store=runGraph(run);
  const documented=await documentedStatuses(questionsPath);
  const engine=new QueryEngine();
  const results=[];
  for(const q of QUESTIONS){
    const stream=await engine.queryBindings(q.sparql,{sources:[store]});
    const rows=await stream.toArray();
    const answered=rows.length>0;
    const met=q.expect==='some'?answered:!answered;
    const base=q.id.replace(/[a-z]$/,'');
    results.push({id:q.id,question:q.question,expect:q.expect,rows:rows.length,expectationMet:met,
      documentedStatus:documented[base]??null,
      sample:rows.slice(0,2).map(r=>Object.fromEntries([...r].map(([k,v])=>[k.value,v.value.slice(0,80)]))),
      because:q.because??null});
  }
  return {check:'04-competency-questions',ranAt:new Date().toISOString(),
    environment:{engine:'Comunica 4.5.0 over an N3 store',runtime:process.version,reasoning:'none; asserted triples only'},
    fixture:{receipt:receiptPath.split('/').pop(),sha256:digest,schema:run.schema,runId:run.runId,
      receipts:(run.receipts||[]).length,executedNodes:(run.trace||[]).length,triples:store.size},
    questions:results,
    summary:{total:results.length,expectationsMet:results.filter(r=>r.expectationMet).length,
      refusalsHeld:results.filter(r=>r.expect==='none'&&r.expectationMet).length,
      refusalsTotal:results.filter(r=>r.expect==='none').length}};
}

if(import.meta.url===`file://${process.argv[1]}`){
  const report=await run('./fixtures/run-receipt-old-naledi.json','../../fieldwork/docs/competency-questions.md');
  await mkdir('./results',{recursive:true});
  await writeFile('./results/check-04-competency.json',JSON.stringify(report,null,2)+'\n');
  const f=report.fixture;
  console.log(`receipt ${f.receipt} · ${f.receipts} receipts · ${f.executedNodes} nodes · ${f.triples} triples`);
  for(const q of report.questions){
    const mark=q.expectationMet?'ok  ':'DRIFT';
    const doc=q.documentedStatus?` [documented: ${q.documentedStatus}]`:'';
    console.log(`  ${mark} ${q.id.padEnd(4)} ${q.rows} row(s), expected ${q.expect}${doc}`);
  }
  const s=report.summary;
  console.log(`\n${s.expectationsMet} of ${s.total} expectations met · ${s.refusalsHeld} of ${s.refusalsTotal} refusals held`);
  console.log('wrote results/check-04-competency.json');
}
