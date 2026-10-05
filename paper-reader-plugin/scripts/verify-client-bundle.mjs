import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const bundle = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8')
let registration

runInNewContext(bundle, {
  window: {
    __ModuleLoader__: {
      load(value) {
        registration = value
      },
    },
  },
})

if (registration?.id !== 'dsh-paper-reader') {
  throw new Error('client bundle did not register dsh-paper-reader')
}
if (typeof registration.factory !== 'function') {
  throw new Error('client bundle registration is missing its factory')
}

const client = registration.factory((specifier) => {
  if (specifier === 'react' || specifier === 'react-dom') return {}
  throw new Error(`unexpected client external: ${specifier}`)
})

if (typeof client?.apply !== 'function' || !Array.isArray(client?.inject)) {
  throw new Error('client bundle factory did not expose the DSH plugin contract')
}
