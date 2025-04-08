export interface Translation {
    english: string;
    chinese: string;
    pinyin: string;
    usage_notes: string;
}

export interface TranslationRequest {
    text: string;
    is_formal: boolean;
    include_pinyin: boolean;
}