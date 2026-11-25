// iwinfo scan entries often contain only a channel. Resolve it in the
// selected radio's band so the table and the spectrum use the same data.
export function numeric(value: any): number | null {
  if (value == null || value === '' || typeof value === 'boolean') return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function channelFrequency(channel: number, band: string): number | null {
  if (!Number.isInteger(channel) || channel < 1) return null;
  if (band === '2g') return channel <= 14 ? channel === 14 ? 2484 : 2407 + channel * 5 : null;
  if (band === '6g') return channel <= 233 ? channel === 2 ? 5935 : 5950 + channel * 5 : null;
  if (band === '5g') return channel <= 196 ? (channel >= 182 ? 4000 : 5000) + channel * 5 : null;
  return null;
}

export function networksForScan(data: any, radio: any) {
  const frequencies = data?.frequencies?.length ? data.frequencies : radio?.frequencies || [];
  const reference = numeric(radio?.frequency) || numeric(frequencies[0]?.mhz || frequencies[0]?.frequency);
  const band = radio?.band || (reference ? reference < 3000 ? '2g' : reference >= 5925 ? '6g' : '5g' : null);
  return (data?.networks || []).map((row: any) => {
    let channel = numeric(row.channel), frequency = numeric(row.frequency) || numeric(row.mhz);
    const rowBand = ['2g','5g','6g'].includes(String(row.band)) ? String(row.band) : [2,5,6].includes(Number(row.band)) ? String(row.band)+'g' : band;
    if (!frequency && channel) {
      const known = frequencies.find((entry: any) => { const mhz = numeric(entry.mhz || entry.frequency); return numeric(entry.channel) === channel && (!rowBand || mhz != null && (mhz < 3000 ? '2g' : mhz >= 5925 ? '6g' : '5g') === rowBand); });
      frequency = numeric(known?.mhz || known?.frequency) || channelFrequency(channel, rowBand);
    }
    if (!channel && frequency) channel = frequency === 2484 ? 14 : frequency === 5935 ? 2
      : (frequency - (frequency < 3000 ? 2407 : frequency >= 5955 ? 5950 : frequency < 5000 ? 4000 : 5000)) / 5;
    let signal = numeric(row.signal);
    if (signal != null && signal >= 2147483648 && signal <= 4294967295) signal -= 4294967296;
    return { ...row, ssid: String(row.ssid ?? ''), bssid: String(row.bssid ?? ''), channel, frequency, signal };
  }).sort((a: any, b: any) => (b.signal ?? -200) - (a.signal ?? -200));
}

function operationFrequency(value: number, primary: number) {
  if (value > 1000) return value;
  return channelFrequency(value, primary < 3000 ? '2g' : primary >= 5925 ? '6g' : '5g') || primary;
}
export function segmentsForNetwork(row: any) {
  const ht = row.ht_operation || {}, offset = String(ht.secondary_channel_offset || '').toLowerCase();
  let width = offset === 'above' || offset === 'below' ? 40 : 20;
  let center = row.frequency + (offset === 'above' ? 10 : offset === 'below' ? -10 : 0);
  let known = !!row.ht_operation && numeric(ht.channel_width) != null || ['above','below'].includes(offset);
  for (const key of ['vht_operation', 'he_operation', 'eht_operation']) {
    const operation = row[key], candidate = numeric(operation?.channel_width);
    if (operation && candidate === 20 && width === 20) known = true;
    if (!operation || candidate == null || candidate <= (key === 'vht_operation' ? 40 : 20)) continue;
    const first = numeric(operation.center_freq_1), second = numeric(operation.center_freq_2);
    if (first == null) continue;
    if (candidate === 8080 && second != null)
      return [first, second].map(value => ({ center: operationFrequency(value, row.frequency), width: 80, known: true }));
    if (![40, 80, 160, 320].includes(candidate)) continue;
    width = candidate; center = operationFrequency(first, row.frequency); known = true;
    if ((candidate === 160 || candidate === 320) && second != null && second > 0) {
      const other = operationFrequency(second, row.frequency);
      if (candidate === 320 || Math.abs(other - center) === 40) center = other;
    }
    if (candidate === 80 && second != null && second !== 0) {
      const other = operationFrequency(second, row.frequency), distance = Math.abs(other - center);
      if (distance === 40) { width = 160; center = other; }
      else if (distance > 40) return [center, other].map(value => ({ center: value, width: 80, known: true }));
    }
  }
  return [{ center, width, known }];
}
