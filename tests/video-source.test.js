import test from 'node:test'
import assert from 'node:assert/strict'
import {videoSource,videoTime} from '../client/src/video-source.js'

test('video playback resolves exact registered IDs and preserves recorded time positions',()=>{
 const source=videoSource('https://youtu.be/M7lc1UVf-VE',83.5)
 assert.equal(source.embed,'https://www.youtube.com/embed/M7lc1UVf-VE?start=83&playsinline=1&controls=1')
 assert.equal(videoSource('https://www.youtube.com/watch?v=M7lc1UVf-VE').kind,'youtube')
 assert.equal(videoSource('https://www.youtube.com/shorts/M7lc1UVf-VE').kind,'youtube')
 assert.equal(videoSource('https://example.org/a.mp4?token=sample',23).embed,'https://example.org/a.mp4?token=sample#t=23')
 for(const input of ['javascript:alert(1)','file:///secret.mp4','https://youtube.com.evil.test/watch?v=M7lc1UVf-VE','https://www.youtube.com/watch?v=invalid','https://example.org/article'])assert.equal(videoSource(input),null)
 assert.equal(videoTime(83.5),'1:23');assert.equal(videoTime(undefined),null)
})
