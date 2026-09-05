import {cents} from "./engine.mjs";
export function parseCsv(text,kind,Papa) {
  if(!Papa?.parse)throw new Error("CSV parser is unavailable");
  if(text.length>5*1024*1024)throw new Error("CSV exceeds the 5 MB demo limit");
  const preview=Papa.parse(text,{preview:1,skipEmptyLines:"greedy",dynamicTyping:false});
  if(preview.errors.length)throw new Error(`CSV row ${(preview.errors[0].row ?? 0)+2}: ${preview.errors[0].message}`);
  const seenHeaders=new Set();
  for(const header of (preview.data?.[0] || []).map(h=>String(h).replace(/^\ufeff/,"").trim())) {
    if(seenHeaders.has(header))throw new Error("Duplicate CSV headers are not allowed");
    seenHeaders.add(header);
  }
  const result=Papa.parse(text,{header:true,skipEmptyLines:"greedy",dynamicTyping:false,transformHeader:h=>h.replace(/^\ufeff/,"").trim()});
  if(result.errors.length)throw new Error(`CSV row ${(result.errors[0].row ?? 0)+2}: ${result.errors[0].message}`);
  if(Object.keys(result.meta.renamedHeaders || {}).length)throw new Error("Duplicate CSV headers are not allowed");
  const required=kind==="summary"?["month","account","amount"]:["id","date","month","account","counterparty","segment","category","amount","status"];
  for(const field of required)if(!result.meta.fields?.includes(field))throw new Error(`Missing ${kind} column: ${field}`);
  if(!result.data.length || result.data.length>10000)throw new Error("CSV must contain 1 to 10,000 data rows");
  return result.data.map((row,index)=>{
    const clean=Object.fromEntries(Object.entries(row).map(([key,value])=>[key,typeof value==="string"?value.trim():value]));
    for(const key of required)if(!clean[key])throw new Error(`CSV row ${index+2}: missing ${key}`);
    try{cents(clean.amount);}catch{throw new Error(`CSV row ${index+2}: amount must be a USD decimal with at most two decimal places`);}
    return clean;
  });
}
