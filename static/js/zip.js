// A store-only (uncompressed) ZIP writer, for exporting the CSV and the traced
// PNGs as one download. PNGs are already compressed, so deflate would buy
// almost nothing, and this keeps the page free of a vendored library.
const Zip = {
  crcTable: null,

  crc32( bytes ) {
    if ( !this.crcTable ) {
      this.crcTable = new Uint32Array( 256 );
      for ( let n = 0; n < 256; n += 1 ) {
        let c = n;
        for ( let k = 0; k < 8; k += 1 ) c = c & 1 ? 0xedb88320 ^ ( c >>> 1 ) : c >>> 1;
        this.crcTable[ n ] = c >>> 0;
      }
    }
    let crc = 0xffffffff;
    for ( let i = 0; i < bytes.length; i += 1 ) crc = this.crcTable[ ( crc ^ bytes[ i ] ) & 0xff ] ^ ( crc >>> 8 );
    return ( crc ^ 0xffffffff ) >>> 0;
  },

  // files: [{ name, data: Uint8Array | string }] -> Blob (application/zip)
  build( files ) {
    const encoder = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;
    const now = new Date();
    const time = ( now.getHours() << 11 ) | ( now.getMinutes() << 5 ) | ( now.getSeconds() >> 1 );
    const date = ( ( now.getFullYear() - 1980 ) << 9 ) | ( ( now.getMonth() + 1 ) << 5 ) | now.getDate();
    files.forEach( ( file ) => {
      const name = encoder.encode( file.name );
      const data = typeof file.data === "string" ? encoder.encode( file.data ) : file.data;
      const crc = this.crc32( data );
      const local = new DataView( new ArrayBuffer( 30 ) );
      local.setUint32( 0 , 0x04034b50 , true );
      local.setUint16( 4 , 20 , true );
      local.setUint16( 6 , 0x0800 , true );      // UTF-8 names
      local.setUint16( 8 , 0 , true );           // stored
      local.setUint16( 10 , time , true );
      local.setUint16( 12 , date , true );
      local.setUint32( 14 , crc , true );
      local.setUint32( 18 , data.length , true );
      local.setUint32( 22 , data.length , true );
      local.setUint16( 26 , name.length , true );
      parts.push( local.buffer , name , data );
      const entry = new DataView( new ArrayBuffer( 46 ) );
      entry.setUint32( 0 , 0x02014b50 , true );
      entry.setUint16( 4 , 20 , true );
      entry.setUint16( 6 , 20 , true );
      entry.setUint16( 8 , 0x0800 , true );
      entry.setUint16( 10 , 0 , true );
      entry.setUint16( 12 , time , true );
      entry.setUint16( 14 , date , true );
      entry.setUint32( 16 , crc , true );
      entry.setUint32( 20 , data.length , true );
      entry.setUint32( 24 , data.length , true );
      entry.setUint16( 28 , name.length , true );
      entry.setUint32( 42 , offset , true );
      central.push( entry.buffer , name );
      offset += 30 + name.length + data.length;
    } );
    const centralSize = central.reduce( ( sum , part ) => sum + part.byteLength , 0 );
    const end = new DataView( new ArrayBuffer( 22 ) );
    end.setUint32( 0 , 0x06054b50 , true );
    end.setUint16( 8 , files.length , true );
    end.setUint16( 10 , files.length , true );
    end.setUint32( 12 , centralSize , true );
    end.setUint32( 16 , offset , true );
    return new Blob( parts.concat( central , [ end.buffer ] ) , { type: "application/zip" } );
  },
};
