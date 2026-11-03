// A store-only (uncompressed) ZIP writer, for exporting the CSV and the traced
// PNGs as one download. PNGs are already compressed, so deflate would buy
// almost nothing, and this keeps the page free of a vendored library.
//
// Exports with the image files themselves can pass 4 GB, so offsets past that
// get ZIP64 records; and an entry can be a symbolic link (the Original-names
// folder), stored the Unix way: its data the relative target, its mode a link.
const Zip = {
  crcTable: null,
  max32: 0xffffffff,
  zip64At: 0xffffffff,   // offsets from here on take ZIP64 records

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

  // files: [{ name, data: Uint8Array | string, link? }] -> Blob (application/zip).
  // link: true makes the entry a symbolic link to data (a relative path).
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
      // Past 4 GB the offset moves to a ZIP64 extra field.
      const far = offset >= this.zip64At;
      const extra = far ? new DataView( new ArrayBuffer( 12 ) ) : null;
      if ( far ) {
        extra.setUint16( 0 , 0x0001 , true );
        extra.setUint16( 2 , 8 , true );
        extra.setBigUint64( 4 , BigInt( offset ) , true );
      }
      const entry = new DataView( new ArrayBuffer( 46 ) );
      entry.setUint32( 0 , 0x02014b50 , true );
      // Made by Unix (3) for a link, so its mode below is read.
      entry.setUint16( 4 , file.link ? 0x0314 : 20 , true );
      entry.setUint16( 6 , far ? 45 : 20 , true );
      entry.setUint16( 8 , 0x0800 , true );
      entry.setUint16( 10 , 0 , true );
      entry.setUint16( 12 , time , true );
      entry.setUint16( 14 , date , true );
      entry.setUint32( 16 , crc , true );
      entry.setUint32( 20 , data.length , true );
      entry.setUint32( 24 , data.length , true );
      entry.setUint16( 28 , name.length , true );
      entry.setUint16( 30 , far ? 12 : 0 , true );
      if ( file.link ) entry.setUint32( 38 , ( 0o120777 << 16 ) >>> 0 , true );
      entry.setUint32( 42 , far ? this.max32 : offset , true );
      central.push( entry.buffer , name );
      if ( far ) central.push( extra.buffer );
      offset += 30 + name.length + data.length;
    } );
    const centralSize = central.reduce( ( sum , part ) => sum + part.byteLength , 0 );
    const tail = [];
    const zip64 = offset >= this.zip64At || files.length >= 0xffff;
    if ( zip64 ) {
      const record = new DataView( new ArrayBuffer( 56 ) );
      record.setUint32( 0 , 0x06064b50 , true );
      record.setBigUint64( 4 , 44n , true );
      record.setUint16( 12 , 45 , true );
      record.setUint16( 14 , 45 , true );
      record.setBigUint64( 24 , BigInt( files.length ) , true );
      record.setBigUint64( 32 , BigInt( files.length ) , true );
      record.setBigUint64( 40 , BigInt( centralSize ) , true );
      record.setBigUint64( 48 , BigInt( offset ) , true );
      const locator = new DataView( new ArrayBuffer( 20 ) );
      locator.setUint32( 0 , 0x07064b50 , true );
      locator.setBigUint64( 8 , BigInt( offset + centralSize ) , true );
      locator.setUint32( 16 , 1 , true );
      tail.push( record.buffer , locator.buffer );
    }
    const end = new DataView( new ArrayBuffer( 22 ) );
    end.setUint32( 0 , 0x06054b50 , true );
    end.setUint16( 8 , zip64 ? 0xffff : files.length , true );
    end.setUint16( 10 , zip64 ? 0xffff : files.length , true );
    end.setUint32( 12 , centralSize , true );
    end.setUint32( 16 , zip64 ? this.max32 : offset , true );
    tail.push( end.buffer );
    return new Blob( parts.concat( central , tail ) , { type: "application/zip" } );
  },
};
