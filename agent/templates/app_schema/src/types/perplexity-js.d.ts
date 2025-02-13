declare module 'perplexity-js' {
    interface PerplexityConfig {
        apiKey: string;
    }

    interface SearchOptions {
        query: string;
        maxResults?: number;
        domainFilter?: {
            include?: string[];
            exclude?: string[];
        };
        searchRecencyFilter?: string;
    }

    interface SearchResponse {
        content: Array<{
            text: string;
        }>;
    }

    export class Perplexity {
        constructor(config: PerplexityConfig);
        search(options: SearchOptions): Promise<SearchResponse>;
    }
} 