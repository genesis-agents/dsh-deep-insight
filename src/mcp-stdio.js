/** Native Agent stdio transport; research execution stays in the owning PIES host. */
import { connect } from 'node:net'
import { createInterface } from 'node:readline'

const socket = connect(process.env.PIES_INSIGHT_PIPE)
socket.on('error', () => { process.exitCode = 1; process.stdin.destroy() })
socket.on('close', () => { process.stdin.destroy() })
socket.write(JSON.stringify({ token: process.env.PIES_INSIGHT_TOKEN }) + '\n')
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
lines.on('line', line => socket.write(line + '\n'))
lines.on('close', () => socket.end())
socket.pipe(process.stdout)
