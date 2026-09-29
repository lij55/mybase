// Local authenticated example for this deployment's legacy JWT mode.
const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors })
  if (req.method !== 'POST') {
    return Response.json({ error: 'Method not allowed' }, { status: 405, headers: cors })
  }
  // The main runtime verifies the JWT signature. This additionally requires a user:
  // a valid, publicly available anon JWT alone must not grant user-only access.
  const response = await fetch(`${Deno.env.get('SUPABASE_URL')}/auth/v1/user`, {
    headers: {
      apikey: Deno.env.get('SUPABASE_ANON_KEY')!,
      Authorization: req.headers.get('Authorization') ?? '',
    },
  })
  if (!response.ok) {
    return Response.json({ error: 'Sign in required' }, { status: 401, headers: cors })
  }
  try {
    const body = await req.json()
    const name = typeof body.name === 'string' ? body.name.slice(0, 100) : 'World'
    return Response.json({ message: `Hello ${name}!` }, { headers: cors })
  } catch {
    return Response.json({ error: 'Invalid JSON body' }, { status: 400, headers: cors })
  }
})
