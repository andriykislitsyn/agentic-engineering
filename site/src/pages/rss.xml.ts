import rss from '@astrojs/rss';
import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { url } from '../url';

export const GET: APIRoute = async ({ site }) => {
  const articles = (await getCollection('articles', ({ data }) => !data.draft)).sort(
    (a, b) => b.data.pubDate.valueOf() - a.data.pubDate.valueOf(),
  );
  return rss({
    title: 'Agentic Engineering',
    description: 'Notes on building, testing, and shipping agent systems.',
    site: new URL(url(), site).href,
    items: articles.map(({ id, data }) => ({
      title: data.title,
      description: data.description,
      pubDate: data.pubDate,
      link: new URL(url(`articles/${id}/`), site).href,
      categories: data.tags,
    })),
  });
};
