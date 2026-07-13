import assert from 'node:assert/strict'

import { consumeSseResponse } from '../src/api/chat.js'

const sseText = [
  'event: token\ndata: {"content":"医疗"}\n\n',
  'event: token\ndata: {"content":"资料"}\n\n',
  'event: sources\ndata: {"sources":[{"file_name":"指南.pdf","page":2,"content":"引用"}]}\n\n',
  'event: done\ndata: {"request_id":"request-1","disclaimer":"仅供学习"}\n\n',
].join('')

const bytes = new TextEncoder().encode(sseText)
// 刻意在中文 UTF-8 字节和 SSE 边界中间切开，模拟真实网络分包。
const splitPoints = [7, 19, 31, 52, 89, 137, bytes.length]
let start = 0
const stream = new ReadableStream({
  pull(controller) {
    const end = splitPoints.shift()
    if (end === undefined) {
      controller.close()
      return
    }
    controller.enqueue(bytes.slice(start, end))
    start = end
  },
})

let answer = ''
let sources = []
let doneData = null

await consumeSseResponse(new Response(stream), {
  onToken(content) { answer += content },
  onSources(value) { sources = value },
  onDone(value) { doneData = value },
})

assert.equal(answer, '医疗资料')
assert.equal(sources[0].file_name, '指南.pdf')
assert.equal(sources[0].page, 2)
assert.equal(doneData.request_id, 'request-1')
console.log('SSE parser test passed')
