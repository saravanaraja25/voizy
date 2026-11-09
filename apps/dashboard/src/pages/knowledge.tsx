import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, FileText, Loader2, Plus, Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { toast } from 'sonner'
import { describeError } from '@/api/client'
import type { DocumentOut } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { Field } from '@/components/field'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { readTextFile } from '@/lib/files'

const MAX_BYTES = 380_000
const COLLECTION = /^[a-z0-9][a-z0-9_-]{0,39}$/
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function titleFromFilename(name: string): string {
  return name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim()
}

function AddDocumentDialog({ collections }: { collections: string[] }) {
  const { client } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [collection, setCollection] = useState('default')
  const [content, setContent] = useState('')
  const [sourceName, setSourceName] = useState('')

  const add = useMutation({
    mutationFn: () =>
      client!.addDocument({ title: title.trim(), content, collection, source_name: sourceName }),
    onSuccess: (d) => {
      void queryClient.invalidateQueries({ queryKey: ['kb'] })
      toast.success(`Added “${d.title}” (${d.chunk_count} sections)`)
      setOpen(false)
      setTitle('')
      setContent('')
      setSourceName('')
    },
    onError: (e) => toast.error(describeError(e)),
  })

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setContent(await readTextFile(file, MAX_BYTES))
      setSourceName(file.name)
      setTitle((t) => t || titleFromFilename(file.name))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not read that file.')
    }
  }

  const ready = title.trim() !== '' && content.trim() !== '' && COLLECTION.test(collection)
  function onSubmit(ev: FormEvent) {
    ev.preventDefault()
    if (ready) add.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> Add document
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Add a document</DialogTitle>
            <DialogDescription>
              Plain text or Markdown works best. Use headings (# Returns) to keep topics separate.
            </DialogDescription>
          </DialogHeader>
          <Field label="Upload a text file (optional)" htmlFor="kb-file" hint=".txt, .md or .csv, up to about 380 KB.">
            <Input id="kb-file" type="file" accept=".txt,.md,.markdown,.csv,text/plain,text/markdown" onChange={(e) => void onFile(e)} />
          </Field>
          <Field label="Title" htmlFor="kb-title">
            <Input id="kb-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
          </Field>
          <Field
            label="Collection"
            htmlFor="kb-collection"
            hint="Agents read one collection. Use different ones for different businesses."
            error={COLLECTION.test(collection) ? undefined : 'Lowercase letters, digits, - and _ only.'}
          >
            <Input id="kb-collection" list="kb-collections" value={collection} onChange={(e) => setCollection(e.target.value)} maxLength={40} />
            <datalist id="kb-collections">
              {collections.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
          <Field label="Document text" htmlFor="kb-content">
            <Textarea id="kb-content" value={content} onChange={(e) => setContent(e.target.value)} rows={8} className="font-mono text-xs" required />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={!ready || add.isPending}>
              {add.isPending && <Loader2 className="animate-spin" />}
              Add to knowledge base
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ViewDocument({ doc }: { doc: DocumentOut }) {
  const { client } = useAuth()
  const [open, setOpen] = useState(false)
  const detail = useQuery({
    queryKey: ['kb', 'doc', doc.id],
    queryFn: () => client!.document(doc.id),
    enabled: !!client && open,
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="link" className="h-auto p-0 font-medium" />}>{doc.title}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{doc.title}</DialogTitle>
          <DialogDescription>
            {doc.chunk_count} sections in “{doc.collection}”. This is how an agent sees it.
          </DialogDescription>
        </DialogHeader>
        <div className="grid max-h-96 gap-3 overflow-y-auto">
          {detail.isPending ? (
            <Skeleton className="h-24" />
          ) : (
            detail.data?.chunks.map((c, i) => (
              <div key={i} className="rounded-md border p-3 text-sm">
                {c.heading && <p className="text-muted-foreground mb-1 text-xs font-medium uppercase">{c.heading}</p>}
                <p className="whitespace-pre-wrap">{c.text}</p>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function TrySearch({ collections }: { collections: string[] }) {
  const { client } = useAuth()
  const [q, setQ] = useState('')
  const [collection, setCollection] = useState(collections[0] ?? 'default')
  const search = useMutation({ mutationFn: () => client!.searchKb(q.trim(), collection) })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Search className="size-4" /> Try a search
        </CardTitle>
        <CardDescription>See what an agent would find for something a caller might say.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (q.trim()) search.mutate()
          }}
        >
          <Input aria-label="What would a caller ask?" placeholder="e.g. how long do I have to return something" value={q} onChange={(e) => setQ(e.target.value)} className="min-w-64 flex-1" />
          <Input aria-label="Collection to search" list="kb-search-collections" value={collection} onChange={(e) => setCollection(e.target.value)} className="w-40" />
          <datalist id="kb-search-collections">
            {collections.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <Button type="submit" disabled={!q.trim() || search.isPending}>
            Search
          </Button>
        </form>
        {search.isError && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{describeError(search.error)}</AlertDescription>
          </Alert>
        )}
        {search.data &&
          (search.data.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing matched. Keyword search needs words that appear in the document; try other wording.
            </p>
          ) : (
            <ol className="grid gap-2" aria-label="Search results">
              {search.data.map((h, i) => (
                <li key={i} className="rounded-md border p-3 text-sm">
                  <p className="text-muted-foreground mb-1 text-xs">
                    {h.document_title}
                    {h.heading ? ` / ${h.heading}` : ''}
                  </p>
                  <p className="whitespace-pre-wrap">{h.text}</p>
                </li>
              ))}
            </ol>
          ))}
      </CardContent>
    </Card>
  )
}

export function KnowledgePage() {
  const { client, can } = useAuth()
  const queryClient = useQueryClient()
  const docs = useQuery({ queryKey: ['kb', 'docs'], queryFn: () => client!.documents(), enabled: !!client })
  const collections = [...new Set((docs.data ?? []).map((d) => d.collection))].sort()
  const remove = useMutation({
    mutationFn: (id: string) => client!.deleteDocument(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['kb'] })
      toast.success('Document deleted')
    },
    onError: (e) => toast.error(describeError(e)),
  })

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
          <p className="text-muted-foreground text-sm">
            Documents your agents can answer from: policies, hours, products, FAQs. Turn it on per agent in
            the editor.
          </p>
        </div>
        {can('kb:manage') && <AddDocumentDialog collections={collections} />}
      </div>

      {docs.isError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{describeError(docs.error)}</AlertDescription>
        </Alert>
      )}

      {docs.isPending ? (
        <div className="grid gap-2" role="status" aria-label="Loading documents">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : (docs.data ?? []).length === 0 ? (
        <Card>
          <CardContent className="grid justify-items-center gap-2 py-10 text-center text-sm">
            <BookOpen className="text-muted-foreground size-6" />
            <p>No documents yet.</p>
            <p className="text-muted-foreground max-w-md">
              Add a returns policy or FAQ, then turn on Knowledge for an agent so it answers from it instead of guessing.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Collection</TableHead>
                <TableHead className="text-right">Sections</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.data!.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <FileText className="text-muted-foreground size-4" />
                      <ViewDocument doc={d} />
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{d.collection}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{d.chunk_count}</TableCell>
                  <TableCell>{dateFormat.format(new Date(d.created_at))}</TableCell>
                  <TableCell className="text-right">
                    {can('kb:manage') && (
                      <AlertDialog>
                        <AlertDialogTrigger render={<Button variant="outline" size="icon" aria-label={`Delete ${d.title}`} />}>
                          <Trash2 />
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Delete “{d.title}”?</AlertDialogTitle>
                            <AlertDialogDescription>
                              Agents stop using it right away. This can’t be undone.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction variant="destructive" onClick={() => remove.mutate(d.id)}>
                              Delete document
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <TrySearch collections={collections} />
        </>
      )}
    </div>
  )
}
