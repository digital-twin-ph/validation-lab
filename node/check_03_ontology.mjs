import {readFile,readdir,writeFile,mkdir} from 'node:fs/promises';
import {Parser,Store,DataFactory} from 'n3';
import {RdfReasoner,INFERRED_GRAPH_IRI} from 'rdf-reasoner-konclude';
const {namedNode:N,quad:Q} = DataFactory;
const FW='urn:fieldwork:',OWL='http://www.w3.org/2002/07/owl#',RDFS='http://www.w3.org/2000/01/rdf-schema#',RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#';
const dir=process.argv[2];
const files=(await readdir(dir)).filter(f=>f.endsWith('.ttl')).sort();
const store=new Store();
for(const f of files)store.addQuads(new Parser({baseIRI:'file://'+dir+'/'+f}).parse(await readFile(dir+'/'+f,'utf8')));
// Fieldwork reuses PROV-O terms but declares no owl:imports, so a reasoner given only its
// files cannot see that prov:Entity and prov:Activity are disjoint. Merge a vendored copy so
// cross-kind conflations are detectable; see vendor/NOTICE.
const provPath=new URL('./vendor/prov.ttl',import.meta.url);
const prov=new Parser({baseIRI:'http://www.w3.org/ns/prov#'}).parse(await readFile(provPath,'utf8'));
const withProv=new Store(store.getQuads(null,null,null,null));withProv.addQuads(prov);
const subjects=p=>new Set(store.getQuads(null,N(RDF+'type'),N(OWL+p),null).map(q=>q.subject.value));
const classes=subjects('Class'),objectProps=subjects('ObjectProperty'),dataProps=subjects('DatatypeProperty');
const external=i=>!i.startsWith(FW);

// --- Structure of the vocabulary itself -------------------------------------
const referenced=new Set();
for(const p of [RDFS+'domain',RDFS+'range',RDFS+'subClassOf'])
  for(const q of store.getQuads(null,N(p),null,null))if(q.object.termType==='NamedNode')referenced.add(q.object.value);
const undeclaredFw=[...referenced].filter(i=>i.startsWith(FW)&&!classes.has(i)).sort();
const has=(s,p)=>store.getQuads(N(s),N(p),null,null).length>0;
const classesWithoutLabel=[...classes].filter(c=>!external(c)&&!has(c,RDFS+'label')).sort();
const classesWithoutComment=[...classes].filter(c=>!external(c)&&!has(c,RDFS+'comment')).sort();
const props=[...objectProps,...dataProps].filter(p=>!external(p));
const propsWithoutDomain=props.filter(p=>!has(p,RDFS+'domain')).sort();
const propsWithoutRange=props.filter(p=>!has(p,RDFS+'range')).sort();

// --- Can the ontology express the distinctions its audit insists on? --------
const auditTerms={
  'Widget definition':'WidgetDefinition','Canvas node plan':'CanvasNodePlan','Workflow node plan':'WorkflowNodePlan',
  'Workflow step':'WorkflowStep','Study area':'StudyArea','Acquisition buffer':'AcquisitionBoundary','Clipping boundary':'ClippingBoundary',
  'Catchment':'Catchment','Isochrone':'NetworkIsochrone','Evidence reference':'EvidenceReference','Presentation':'Presentation',
  'Chart specification':'ChartSpecification','Donut geomasking':'DonutGeomasking','H3 cell aggregate':'HexAggregation',
  'Mean center':'MeanCenterComputation','Point-set comparison':'PointSetComparison'};
const termMapping=Object.entries(auditTerms).map(([term,local])=>({
  term,class:local?FW+local:null,declared:local?classes.has(FW+local):false}));

// --- OWL 2 DL reasoning ----------------------------------------------------
const reasoner=new RdfReasoner({});
const consistency=await reasoner.checkConsistency(store);
const unsatisfiable=await reasoner.getUnsatisfiableClasses(store);
// classify() writes its results into the store's inferred named graph rather than returning them.
const classifyStore=new Store(store.getQuads(null,null,null,null));
await reasoner.classify(classifyStore);
const classified=classifyStore.getQuads(null,null,null,N(INFERRED_GRAPH_IRI));
const asserted=new Set(store.getQuads(null,N(RDFS+'subClassOf'),null,null).map(q=>q.subject.value+' '+q.object.value));
const inferredSubsumptions=classified.filter(q=>q.predicate.value===RDFS+'subClassOf'
  &&q.subject.value.startsWith(FW)&&q.object.value.startsWith(FW)
  &&q.subject.value!==q.object.value&&!asserted.has(q.subject.value+' '+q.object.value));

// --- Probe: conflate terms the audit says must remain distinct --------------
// Same-kind pairs the vocabulary now asserts disjoint: each must be caught on its own.
const sameKind=[[FW+'StudyArea',FW+'ClippingBoundary'],[FW+'StudyArea',FW+'Catchment'],
  [FW+'CanvasNodePlan',FW+'WorkflowNodePlan'],[FW+'WidgetDefinition',FW+'WorkflowNodePlan'],
  [FW+'Presentation',FW+'SpatialOperation']].filter(([a,b])=>classes.has(a)&&classes.has(b));
// Cross-kind pairs, where the contradiction is PROV-O's rather than Fieldwork's.
const crossKind=[[FW+'StudyArea',FW+'AreaBuffer'],[FW+'Catchment',FW+'NetworkIsochrone']]
  .filter(([a,b])=>classes.has(a)&&classes.has(b));
const probe=async(base,[a,b])=>{
  const graph=new Store(base.getQuads(null,null,null,null));
  const s=N('urn:fieldwork:probe:conflation');
  graph.addQuad(Q(s,N(RDF+'type'),N(a)));graph.addQuad(Q(s,N(RDF+'type'),N(b)));
  return await reasoner.checkConsistency(graph)===true;
};
const sameKindResults=[];for(const p of sameKind)sameKindResults.push({pair:p.map(i=>i.replace(FW,'fw:')).join(' + '),consistent:await probe(store,p)});
const crossKindResults=[];for(const p of crossKind)crossKindResults.push({pair:p.map(i=>i.replace(FW,'fw:')).join(' + '),
  consistentWithoutProv:await probe(store,p),consistentWithProv:await probe(withProv,p)});
await reasoner.terminate();

const report={check:'03-ontology-structure-and-meaning',ranAt:new Date().toISOString(),
  engine:{reasoner:'Konclude via rdf-reasoner-konclude 0.7.2 (LGPL-3.0-or-later)',parser:'n3 2.13.8',runtime:process.version},
  input:{directory:dir,files,triples:store.size},
  declared:{classes:[...classes].filter(c=>!external(c)).length,objectProperties:objectProps.size,datatypeProperties:dataProps.size,
    subClassOf:store.getQuads(null,N(RDFS+'subClassOf'),null,null).length,
    domain:store.getQuads(null,N(RDFS+'domain'),null,null).length,range:store.getQuads(null,N(RDFS+'range'),null,null).length},
  strongAxioms:Object.fromEntries(['disjointWith','equivalentClass','FunctionalProperty','InverseFunctionalProperty','inverseOf','someValuesFrom','allValuesFrom','maxCardinality','minCardinality','unionOf','intersectionOf','complementOf','Restriction']
    .map(a=>[a,store.getQuads(null,null,N(OWL+a),null).length+store.getQuads(null,N(OWL+a),null,null).length])),
  structure:{undeclaredFieldworkTermsInDomainRangeOrSubclass:undeclaredFw,classesWithoutLabel,classesWithoutComment,
    propertiesWithoutDomain:propsWithoutDomain,propertiesWithoutRange:propsWithoutRange},
  auditTermCoverage:termMapping,
  reasoning:{inferredTriplesTotal:classified.length,consistent:consistency===true,unsatisfiableClasses:(unsatisfiable||[]).map(c=>c.value??c),
    inferredFieldworkSubsumptionsBeyondAsserted:inferredSubsumptions.map(q=>`${q.subject.value} rdfs:subClassOf ${q.object.value}`)},
  conflationProbe:{
    sameKindCaught:sameKindResults.filter(r=>!r.consistent).length,sameKindTotal:sameKindResults.length,sameKind:sameKindResults,
    crossKindCaughtWithProv:crossKindResults.filter(r=>!r.consistentWithProv).length,crossKindTotal:crossKindResults.length,crossKind:crossKindResults}};
// Write the report, and print a summary, matching the Python checks.
const out=new URL('./results/check-03-ontology.json',import.meta.url);
await mkdir(new URL('./results/',import.meta.url),{recursive:true});
await writeFile(out,JSON.stringify(report,null,2)+'\n');
const s=report.structure,p=report.conflationProbe;
console.log(`files ${files.length} · triples ${report.input.triples} · classes ${report.declared.classes} · properties ${report.declared.objectProperties+report.declared.datatypeProperties}`);
console.log(`strong axioms: ${Object.values(report.strongAxioms).reduce((a,b)=>a+b,0)} (disjointness, cardinality, restrictions, property characteristics)`);
console.log(`consistent: ${report.reasoning.consistent} · unsatisfiable classes: ${report.reasoning.unsatisfiableClasses.length} · inferred subsumptions beyond asserted: ${report.reasoning.inferredFieldworkSubsumptionsBeyondAsserted.length}`);
console.log(`structure: ${s.undeclaredFieldworkTermsInDomainRangeOrSubclass.length} undeclared terms · ${s.classesWithoutLabel.length} classes without a label · ${s.propertiesWithoutDomain.length} properties without a domain`);
console.log(`audit terms with no class: ${report.auditTermCoverage.filter(t=>!t.declared).map(t=>t.term).join(', ')||'none'}`);
console.log(`conflation probe, same kind: ${p.sameKindCaught} of ${p.sameKindTotal} caught by Fieldwork's own axioms`);
for(const r of p.sameKind)console.log(`   ${r.consistent?'MISSED':'caught'}  ${r.pair}`);
console.log(`conflation probe, cross kind: ${p.crossKindCaughtWithProv} of ${p.crossKindTotal} caught once PROV-O is merged`);
for(const r of p.crossKind)console.log(`   without PROV-O ${r.consistentWithoutProv?'missed':'caught'} · with PROV-O ${r.consistentWithProv?'MISSED':'caught'}  ${r.pair}`);
console.log(`wrote results/check-03-ontology.json`);
