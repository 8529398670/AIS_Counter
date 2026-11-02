// A minimal Excel (.xlsx) writer for the batch reports: one worksheet per
// sheet, a bold, frozen header row with a filter, numbers as numbers and
// everything else as inline text. Built on Zip (a stored ZIP, which Excel,
// Numbers and LibreOffice all open), so the page stays free of a vendored
// spreadsheet library.
const Xlsx = {
  type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

  escape( text ) {
    // Control characters other than tab and newline are not allowed in XML.
    return String( text ).replace( /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g , "" )
      .replace( /&/g , "&amp;" ).replace( /</g , "&lt;" ).replace( />/g , "&gt;" ).replace( /"/g , "&quot;" );
  },

  // 0 -> "A", 26 -> "AA".
  column( index ) {
    let name = "";
    for ( let n = index + 1; n > 0; n = Math.floor( ( n - 1 ) / 26 ) ) name = String.fromCharCode( 65 + ( n - 1 ) % 26 ) + name;
    return name;
  },

  cell( value , ref , style ) {
    const s = style ? ' s="' + style + '"' : "";
    if ( value == null || value === "" ) return "";
    if ( typeof value === "number" && Number.isFinite( value ) ) return '<c r="' + ref + '"' + s + "><v>" + value + "</v></c>";
    if ( typeof value === "boolean" ) return '<c r="' + ref + '"' + s + ' t="b"><v>' + ( value ? 1 : 0 ) + "</v></c>";
    return '<c r="' + ref + '"' + s + ' t="inlineStr"><is><t xml:space="preserve">' + this.escape( value ) + "</t></is></c>";
  },

  // A width per column from its longest value, within reason.
  widths( sheet ) {
    return sheet.cols.map( ( header , i ) => {
      const longest = sheet.rows.reduce( ( n , row ) => Math.max( n , row[ i ] == null ? 0 : String( row[ i ] ).length ) , String( header ).length );
      return Math.min( 60 , Math.max( 6 , longest + 2 ) );
    } );
  },

  sheetXml( sheet ) {
    const last = this.column( Math.max( 0 , sheet.cols.length - 1 ) ) + ( sheet.rows.length + 1 );
    const rows = [ sheet.cols ].concat( sheet.rows ).map( ( row , r ) => '<row r="' + ( r + 1 ) + '">'
      + row.map( ( value , c ) => this.cell( value , this.column( c ) + ( r + 1 ) , r === 0 ? 1 : 0 ) ).join( "" ) + "</row>" );
    const cols = this.widths( sheet ).map( ( w , i ) => '<col min="' + ( i + 1 ) + '" max="' + ( i + 1 ) + '" width="' + w + '" customWidth="1"/>' );
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
      + '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
      + ( cols.length ? "<cols>" + cols.join( "" ) + "</cols>" : "" )
      + "<sheetData>" + rows.join( "" ) + "</sheetData>"
      + ( sheet.cols.length ? '<autoFilter ref="A1:' + last + '"/>' : "" )
      + "</worksheet>";
  },

  // Excel's rules: at most 31 characters, none of []:*?/\ , unique.
  names( sheets ) {
    const seen = new Set();
    return sheets.map( ( sheet , i ) => {
      let name = String( sheet.name || "Sheet" + ( i + 1 ) ).replace( /[\[\]:*?\/\\]/g , " " ).slice( 0 , 31 ).trim() || "Sheet" + ( i + 1 );
      for ( let n = 2; seen.has( name.toLowerCase() ); n += 1 ) name = name.slice( 0 , 27 ) + " (" + n + ")";
      seen.add( name.toLowerCase() );
      return name;
    } );
  },

  // sheets: [{ name, cols: [header], rows: [[value]] }] -> Blob
  build( sheets ) {
    const names = this.names( sheets );
    const xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
    const main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
    const rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    const files = [
      { name: "[Content_Types].xml" , data: xml + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        + '<Default Extension="xml" ContentType="application/xml"/>'
        + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + sheets.map( ( _ , i ) => '<Override PartName="/xl/worksheets/sheet' + ( i + 1 ) + '.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' ).join( "" )
        + "</Types>" },
      { name: "_rels/.rels" , data: xml + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" Type="' + rel + '/officeDocument" Target="xl/workbook.xml"/></Relationships>' },
      { name: "xl/workbook.xml" , data: xml + '<workbook xmlns="' + main + '" xmlns:r="' + rel + '"><sheets>'
        + names.map( ( name , i ) => '<sheet name="' + this.escape( name ) + '" sheetId="' + ( i + 1 ) + '" r:id="rId' + ( i + 1 ) + '"/>' ).join( "" )
        + "</sheets>"
        // The filter ranges, so Excel shows them as filters.
        + "<definedNames>" + sheets.map( ( sheet , i ) => sheet.cols.length ? '<definedName name="_xlnm._FilterDatabase" localSheetId="' + i + '" hidden="1">\''
          + this.escape( names[ i ].replace( /'/g , "''" ) ) + "'!$A$1:$" + this.column( sheet.cols.length - 1 ) + "$" + ( sheet.rows.length + 1 ) + "</definedName>" : "" ).join( "" )
        + "</definedNames></workbook>" },
      { name: "xl/_rels/workbook.xml.rels" , data: xml + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + sheets.map( ( _ , i ) => '<Relationship Id="rId' + ( i + 1 ) + '" Type="' + rel + '/worksheet" Target="worksheets/sheet' + ( i + 1 ) + '.xml"/>' ).join( "" )
        + '<Relationship Id="rId' + ( sheets.length + 1 ) + '" Type="' + rel + '/styles" Target="styles.xml"/></Relationships>' },
      { name: "xl/styles.xml" , data: xml + '<styleSheet xmlns="' + main + '">'
        + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        + '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        + '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        + "</styleSheet>" },
    ];
    sheets.forEach( ( sheet , i ) => files.push( { name: "xl/worksheets/sheet" + ( i + 1 ) + ".xml" , data: this.sheetXml( sheet ) } ) );
    return new Blob( [ Zip.build( files ) ] , { type: this.type } );
  },
};
