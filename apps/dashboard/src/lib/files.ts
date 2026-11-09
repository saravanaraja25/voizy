/** Read a user-chosen text file in the browser. Nothing is uploaded until the user submits. */
export function readTextFile(file: File, maxBytes: number): Promise<string> {
  return new Promise((resolve, reject) => {
    if (file.size > maxBytes) {
      reject(new Error(`That file is too large (limit ${Math.round(maxBytes / 1000)} KB).`))
      return
    }
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('Could not read that file.'))
    reader.readAsText(file)
  })
}
