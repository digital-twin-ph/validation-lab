// Executable competency questions. Each one is a query over an exported run graph plus the
// expectation its documented status implies. The point is not only to answer the question
// but to detect drift: if the markdown list claims a question is answerable and the query
// returns nothing, one of the two is wrong.
//
// Documented statuses live in fieldwork/docs/experiments/44-ontology-competency-questions.md and are compared at run
// time. Queries match asserted triples only: no reasoning is applied here, so a query must
// not rely on subclass inference.
const PREFIXES=`
PREFIX fw: <urn:fieldwork:>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
`;
export const QUESTIONS=[
 {id:'P1',expect:'some',question:'Which widget, at which version and digest, produced this result?',
  sparql:`SELECT ?plan ?widget ?version ?digest WHERE { ?plan a fw:WorkflowNodePlan; fw:widget ?widget; fw:catalogVersion ?version; fw:catalogDigest ?digest }`},
 {id:'P2',expect:'some',question:'What parameters did this execution use?',
  sparql:`SELECT ?subject ?parameter ?value WHERE { ?subject ?parameter ?value
    VALUES ?parameter { fw:searchRadiusKm fw:spacingMetres fw:proxyMinutes fw:groupingField fw:chartMark } }`},
 {id:'P3',expect:'some',question:'Which upstream results did this one consume?',
  sparql:`SELECT ?step ?used WHERE { ?step a fw:WorkflowStep . ?activity prov:used ?used }`},
 {id:'P5',expect:'none',question:'Is any individual both a draft canvas plan and an observed workflow plan?',
  sparql:`SELECT ?both WHERE { ?both a fw:CanvasNodePlan, fw:WorkflowNodePlan }`,
  because:'The two are disjoint. A result here would mean a receipt conflates a draft with an execution.'},
 {id:'S1',expect:'some',question:'What geographic scope does this analysis report on?',
  sparql:`SELECT ?feature ?geometry WHERE { ?feature a geo:Feature; geo:hasGeometry ?geometry }`},
 {id:'S1b',expect:'some',question:'Is that scope typed as a study area, rather than only as a feature?',
  sparql:`SELECT ?area WHERE { ?area a fw:StudyArea }`,
  because:'A reviewer looking for the reporting boundary needs to find it by its role, not by guessing which feature it is.'},
 {id:'S4',expect:'some',question:'In which CRS and axis order are these coordinates?',
  sparql:`SELECT ?geometry ?wkt WHERE { ?geometry geo:asWKT ?wkt FILTER(CONTAINS(STR(?wkt), "CRS84")) }`},
 {id:'S5',expect:'none',question:'Which transformation produced these coordinates, with which library and datum handling?',
  sparql:`SELECT ?subject ?predicate ?value WHERE { ?subject ?predicate ?value
    VALUES ?predicate { fw:sourceCRS fw:targetCRS fw:datumShift fw:transformationLibrary } }`,
  because:'Documented as not answerable: reprojection provenance travels as opaque JSON, not typed RDF. A result here would mean the gap has been closed and the list is stale.'},
 {id:'D1',expect:'some',question:'How many records had no location, and were they retained?',
  sparql:`SELECT ?dataset ?count WHERE { ?dataset fw:missingLocationCount ?count }`},
 {id:'E1',expect:'some',question:'What assertion did the reasoner derive about a subject?',
  sparql:`SELECT ?subject ?level WHERE { ?subject fw:evidenceLevel ?level }`},
 {id:'V1',expect:'some',question:'Did this view only display existing results?',
  sparql:`SELECT ?view WHERE { ?view a ?kind VALUES ?kind { fw:MapView fw:TableView fw:ChartView } }`},
 {id:'V1b',expect:'none',question:'Is any view also a spatial operation?',
  sparql:`SELECT ?both WHERE { ?both a fw:SpatialOperation . ?both a ?kind VALUES ?kind { fw:MapView fw:TableView fw:ChartView } }`,
  because:'Presentation and spatial operation are disjoint. A result would mean a view claims to have computed something.'},
 {id:'R1',expect:'none',question:'How many people live in this catchment?',
  sparql:`SELECT ?subject ?value WHERE { ?subject ?predicate ?value
    VALUES ?predicate { fw:populationCount fw:population fw:residents } }`,
  because:'Refused by design. Counts are of records or memberships, never of population, so no term should answer this.'},
].map(q=>({...q,sparql:PREFIXES+q.sparql}));
