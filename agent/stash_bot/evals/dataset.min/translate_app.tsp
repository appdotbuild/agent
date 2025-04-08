model Translation {
    english: string;
    chinese: string;
    pinyin: string;
    usage_notes: string;
}

model TranslationRequest {
    text: string;
    is_formal: boolean;
    include_pinyin: boolean;
}

interface TranslationBot {
    @llm_func(1)
    translate(request: TranslationRequest): Translation;

    @llm_func(2)
    translateWithContext(request: TranslationRequest, context: string): Translation;
}