// Google Places (New) + Geocoding — entity normalization for leads (API key via Doppler)

export interface MapsEntity {
  place_id: string;
  name: string;
  formatted_address: string;
  lat: number;
  lng: number;
  primary_type?: string;
  website_uri?: string;
  phone?: string;
  resolved_at: string;
}

function mapsApiKey(): string | undefined {
  return process.env.GOOGLE_MAPS_API_KEY?.trim();
}

export function isMapsAvailable(): boolean {
  return Boolean(mapsApiKey());
}

export async function resolveMapsPlace(input: {
  owner_name?: string | null;
  property_address?: string | null;
  city?: string | null;
  state?: string | null;
  jurisdiction?: string | null;
}): Promise<MapsEntity | null> {
  const apiKey = mapsApiKey();
  if (!apiKey) return null;

  const ownerClean = (input.owner_name || '')
    .replace(/\s+(LLC|INC|CORP|LTD|CO\.?|L\.L\.C\.?|C\/O.*)/gi, '')
    .trim();
  const location = [input.city, input.jurisdiction, input.state || 'KY'].filter(Boolean).join(', ');

  const queries: string[] = [];
  if (ownerClean && location) queries.push(`${ownerClean} ${location}`);
  if (input.property_address && location) queries.push(`${input.property_address} ${location}`);
  if (!queries.length) return null;

  for (const textQuery of queries) {
    const place = await placesTextSearch(textQuery, apiKey);
    if (place) {
      const geo = await geocodeAddress(place.formatted_address, apiKey);
      return {
        ...place,
        lat: geo?.lat ?? place.lat,
        lng: geo?.lng ?? place.lng,
        resolved_at: new Date().toISOString(),
      };
    }
  }

  return null;
}

async function placesTextSearch(
  textQuery: string,
  apiKey: string
): Promise<Omit<MapsEntity, 'resolved_at'> | null> {
  const fieldMask = [
    'places.id',
    'places.displayName',
    'places.formattedAddress',
    'places.location',
    'places.primaryType',
    'places.websiteUri',
    'places.nationalPhoneNumber',
  ].join(',');

  const res = await fetch('https://places.googleapis.com/v1/places:searchText', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Goog-Api-Key': apiKey,
      'X-Goog-FieldMask': fieldMask,
    },
    body: JSON.stringify({ textQuery, maxResultCount: 1 }),
  });

  if (!res.ok) {
    console.warn('Places search failed:', res.status, await res.text());
    return null;
  }

  const data = (await res.json()) as {
    places?: Array<{
      id?: string;
      displayName?: { text?: string };
      formattedAddress?: string;
      location?: { latitude?: number; longitude?: number };
      primaryType?: string;
      websiteUri?: string;
      nationalPhoneNumber?: string;
    }>;
  };

  const p = data.places?.[0];
  if (!p?.id || !p.formattedAddress) return null;

  return {
    place_id: p.id,
    name: p.displayName?.text || textQuery,
    formatted_address: p.formattedAddress,
    lat: p.location?.latitude ?? 0,
    lng: p.location?.longitude ?? 0,
    primary_type: p.primaryType,
    website_uri: p.websiteUri,
    phone: p.nationalPhoneNumber,
  };
}

async function geocodeAddress(
  address: string,
  apiKey: string
): Promise<{ lat: number; lng: number } | null> {
  const params = new URLSearchParams({ address, key: apiKey });
  const res = await fetch(`https://maps.googleapis.com/maps/api/geocode/json?${params}`);
  if (!res.ok) return null;

  const data = (await res.json()) as {
    results?: Array<{ geometry?: { location?: { lat?: number; lng?: number } } }>;
  };
  const loc = data.results?.[0]?.geometry?.location;
  if (loc?.lat == null || loc?.lng == null) return null;
  return { lat: loc.lat, lng: loc.lng };
}
