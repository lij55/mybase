// Install in your existing Vite frontend: npm install @supabase/supabase-js
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)

export async function signIn(email: string, password: string) {
  const { data, error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) throw error
  return data
}

export async function addTodo(title: string) {
  // user_id is assigned by auth.uid() inside Postgres; RLS enforces ownership.
  const { data, error } = await supabase.from('todos').insert({ title }).select().single()
  if (error) throw error
  return data
}

export async function listTodos() {
  const { data, error } = await supabase.from('todos').select('*').order('created_at')
  if (error) throw error
  return data
}

export async function uploadFile(file: File) {
  const { data: { user }, error: authError } = await supabase.auth.getUser()
  if (authError) throw authError
  if (!user) throw new Error('请先登录')
  // Use an ASCII object key; keep the original display name in your own metadata.
  const path = `${user.id}/${crypto.randomUUID()}`
  const { data, error } = await supabase.storage.from('user-files').upload(path, file)
  if (error) throw error
  return data
}

export function watchTodos(userId: string, refresh: () => void) {
  const channel = supabase.channel(`todos-${userId}`)
    .on('postgres_changes', {
      event: '*', schema: 'public', table: 'todos', filter: `user_id=eq.${userId}`,
    }, refresh)
    .subscribe()
  // Invoke this cleanup when the page unmounts or the user signs out.
  return () => supabase.removeChannel(channel)
}
