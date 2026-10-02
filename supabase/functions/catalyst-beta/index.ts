import { createClient } from 'npm:@supabase/supabase-js@2.112.3';
import { createCatalystHandler } from './handler.mjs';
Deno.serve(createCatalystHandler({ createClient, env: (name: string) => Deno.env.get(name) }));
